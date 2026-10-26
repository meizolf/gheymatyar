"""A Pioneers product has at most one active supplier product per supplier."""

from __future__ import annotations

import threading
import time
from decimal import Decimal
from pathlib import Path

import pytest

import gheymatyar.repositories.mapping_repository as mapping_repository
from gheymatyar.domain.enums import MappingType, MatchStatus
from gheymatyar.domain.product import PioneersProduct
from gheymatyar.domain.supplier_item import SupplierPriceItem
from gheymatyar.repositories.mapping_repository import MappingRepository
from gheymatyar.repositories.supplier_repository import SupplierRepository
from gheymatyar.services.mapping_uniqueness import (
    DUPLICATE_TARGET_WARNING,
    DuplicateMappingTargetError,
)
from gheymatyar.services.matching import SavedNameMapping, match_supplier_items
from gheymatyar.services.name_normalization import normalize_product_name
from gheymatyar.services.product_identity import supplier_product_identity
from gheymatyar.suppliers.azin_pipe import AzinPipeProcessor

# Exact-name match of this Azin item holds Pioneers code 11489 in the fixtures.
HOLDER_OF_11489 = "819121025"


def _session(client, excel: Path, pdf: Path) -> tuple[str, list[dict]]:
    session_id = client.post("/api/sessions").json()["session_id"]
    with excel.open("rb") as handle:
        uploaded = client.post(
            f"/api/sessions/{session_id}/pioneers-excel",
            files={"file": ("p.xlsx", handle, "application/octet-stream")},
        )
    assert uploaded.status_code == 200, uploaded.text
    with pdf.open("rb") as handle:
        parsed = client.post(
            f"/api/sessions/{session_id}/supplier-pdf",
            data={"supplier_key": "azin_pipe"},
            files={"file": ("azin.pdf", handle, "application/pdf")},
        )
    assert parsed.status_code == 200, parsed.text
    matched = client.post(f"/api/sessions/{session_id}/match")
    assert matched.status_code == 200, matched.text
    return session_id, matched.json()["candidates"]


def _free_products(client, session_id: str, candidates: list[dict], count: int):
    """Pioneers products with a code that no matched supplier product holds."""
    taken = {c["row_number"] for c in candidates if c["status"] == "MATCHED"}
    products = client.app.state.processing.get_session(session_id).products
    free = [p for p in products if p.code and p.row_number not in taken]
    assert len(free) >= count
    return free[:count]


def _unmatched(candidates: list[dict], count: int) -> list[dict]:
    rows = [c for c in candidates if c["status"] in {"UNMATCHED", "AMBIGUOUS"}]
    assert len(rows) >= count
    return rows[:count]


def _confirm(client, session_id: str, candidate: dict, row_number: int, save: bool = True):
    return client.post(
        f"/api/sessions/{session_id}/candidates/{candidate['candidate_id']}/confirm-mapping",
        json={"pioneers_row_number": row_number, "save": save},
    )


def _saved(client) -> list[dict]:
    response = client.get("/api/suppliers/azin_pipe/mappings")
    assert response.status_code == 200, response.text
    return response.json()["mappings"]


def test_second_product_on_the_same_pioneers_product_is_rejected_with_409(
    client, pioneers_azin_excel: Path, azin_pdf: Path
) -> None:
    session_id, candidates = _session(client, pioneers_azin_excel, azin_pdf)
    a, b = _unmatched(candidates, 2)
    target, other = _free_products(client, session_id, candidates, 2)

    assert _confirm(client, session_id, a, target.row_number).status_code == 200

    rejected = _confirm(client, session_id, b, target.row_number)
    assert rejected.status_code == 409, rejected.text
    detail = rejected.json()["detail"]
    assert detail["code"] == "duplicate_mapping_target"
    assert detail["pioneers_code"] == target.code
    assert detail["pioneers_name"] == target.name
    assert [c["supplier_name"] for c in detail["conflicts"]] == [a["supplier_name"]]
    assert detail["conflicts"][0]["source"] == "saved_mapping"
    assert target.code in detail["message"]
    # Nothing was saved for B, and A's decision is untouched.
    saved = _saved(client)
    assert [m["supplier_name_raw"] for m in saved] == [a["supplier_name"]]
    assert saved[0]["pioneers_code"] == target.code

    # B can take a different, free product.
    assert _confirm(client, session_id, b, other.row_number).status_code == 200


def test_exact_name_holder_blocks_a_manual_mapping_to_11489(
    client, pioneers_azin_excel: Path, azin_pdf: Path
) -> None:
    session_id, candidates = _session(client, pioneers_azin_excel, azin_pdf)
    holder = next(c for c in candidates if c["supplier_code"] == HOLDER_OF_11489)
    assert (holder["status"], holder["pioneers_code"]) == ("MATCHED", "11489")
    b = _unmatched(candidates, 1)[0]

    for save in (True, False):
        rejected = _confirm(client, session_id, b, holder["row_number"], save=save)
        assert rejected.status_code == 409, rejected.text
        conflict = rejected.json()["detail"]["conflicts"][0]
        assert conflict["supplier_name"] == holder["supplier_name"]
        assert conflict["source"] == "session_match"
    assert _saved(client) == []


def test_remapping_releases_the_old_target_and_reconfirming_is_not_a_conflict(
    client, pioneers_azin_excel: Path, azin_pdf: Path
) -> None:
    session_id, candidates = _session(client, pioneers_azin_excel, azin_pdf)
    a, b = _unmatched(candidates, 2)
    first, second = _free_products(client, session_id, candidates, 2)

    assert _confirm(client, session_id, a, first.row_number).status_code == 200
    # Reconfirming the unchanged target, saved or not, is not a conflict.
    assert _confirm(client, session_id, a, first.row_number).status_code == 200
    assert _confirm(client, session_id, a, first.row_number, save=False).status_code == 200
    # Moving A releases the first product for B.
    assert _confirm(client, session_id, a, second.row_number).status_code == 200
    assert _confirm(client, session_id, b, first.row_number).status_code == 200
    targets = {m["supplier_name_raw"]: m["pioneers_code"] for m in _saved(client)}
    assert targets == {a["supplier_name"]: second.code, b["supplier_name"]: first.code}


def test_ignoring_releases_and_restoring_flags_without_deleting(
    client, pioneers_azin_excel: Path, azin_pdf: Path
) -> None:
    session_id, candidates = _session(client, pioneers_azin_excel, azin_pdf)
    a, b = _unmatched(candidates, 2)
    (target,) = _free_products(client, session_id, candidates, 1)
    assert _confirm(client, session_id, a, target.row_number).status_code == 200

    ignored = client.post(f"/api/sessions/{session_id}/candidates/{a['candidate_id']}/ignore")
    assert ignored.status_code == 200, ignored.text
    # The ignored product no longer holds its saved target.
    assert _confirm(client, session_id, b, target.row_number).status_code == 200

    restored = client.post(f"/api/sessions/{session_id}/candidates/{a['candidate_id']}/restore")
    assert restored.status_code == 200, restored.text
    current = {
        c["candidate_id"]: c
        for c in client.get(f"/api/sessions/{session_id}/candidates").json()["candidates"]
    }
    # Restoring revalidates: two saved decisions now claim the product, so
    # neither is applied automatically and neither can be exported.
    for candidate in (a, b):
        row = current[candidate["candidate_id"]]
        assert row["status"] == "AMBIGUOUS"
        assert DUPLICATE_TARGET_WARNING in row["warnings"]
        assert row["exportable"] is False
        assert row["suggestions"][0]["row_number"] == target.row_number
    # Both saved decisions are kept and flagged on the mappings page.
    saved = {m["supplier_name_raw"]: m for m in _saved(client)}
    assert set(saved) == {a["supplier_name"], b["supplier_name"]}
    assert saved[a["supplier_name"]]["conflicts_with"] == [b["supplier_name"]]
    assert saved[b["supplier_name"]]["conflicts_with"] == [a["supplier_name"]]


def _seed_duplicate_mappings(client, rows: list[dict], code: str, pioneers_name: str):
    """Save the same Pioneers target for several supplier rows, bypassing the API."""
    database = client.app.state.database
    with database.session() as sess:
        suppliers = SupplierRepository(sess)
        supplier = next(
            (row for row in suppliers.list_all() if row.parser_type == "azin_pipe"), None
        ) or suppliers.create(name="آذین لوله", parser_type="azin_pipe")
        for row in rows:
            MappingRepository(sess).create(
                supplier_id=supplier.id,
                supplier_name_raw=row["supplier_name"],
                supplier_name_normalized=AzinPipeProcessor().normalize_supplier_name(
                    row["supplier_name"]
                ),
                supplier_code=row["supplier_code"],
                unit=row["source_unit"],
                pioneers_name_raw=pioneers_name,
                pioneers_code=code,
                mapping_type=MappingType.MANUAL,
            )


def test_duplicates_already_in_sqlite_are_flagged_and_kept(
    client, pioneers_azin_excel: Path, azin_pdf: Path
) -> None:
    session_id, candidates = _session(client, pioneers_azin_excel, azin_pdf)
    a, b = _unmatched(candidates, 2)
    (target,) = _free_products(client, session_id, candidates, 1)
    _seed_duplicate_mappings(client, [a, b], target.code, target.name)

    saved = _saved(client)
    assert len(saved) == 2
    assert all(m["conflicts_with"] for m in saved)

    rematched = client.post(f"/api/sessions/{session_id}/match").json()["candidates"]
    by_name = {c["supplier_name"]: c for c in rematched}
    for name in (a["supplier_name"], b["supplier_name"]):
        row = by_name[name]
        # Neither saved mapping wins; both wait for the user and cannot export.
        assert row["status"] == "AMBIGUOUS"
        assert DUPLICATE_TARGET_WARNING in row["warnings"]
        assert row["suggestions"][0]["pioneers_code"] == target.code
        assert row["exportable"] is False
    assert len(_saved(client)) == 2

    # Editing one of them onto its own (unchanged) target is still a conflict
    # with the other; moving it elsewhere resolves both.
    first_id = saved[0]["id"]
    conflict = client.put(
        f"/api/suppliers/azin_pipe/mappings/{first_id}",
        json={"pioneers_name_raw": target.name, "pioneers_code": target.code},
    )
    assert conflict.status_code == 409, conflict.text
    moved = client.put(
        f"/api/suppliers/azin_pipe/mappings/{first_id}",
        json={"pioneers_name_raw": "کالای دیگر", "pioneers_code": "99999"},
    )
    assert moved.status_code == 200, moved.text
    assert all(m["conflicts_with"] == [] for m in _saved(client))


def test_editing_a_saved_mapping_onto_a_taken_product_is_rejected(
    client, pioneers_azin_excel: Path, azin_pdf: Path
) -> None:
    session_id, candidates = _session(client, pioneers_azin_excel, azin_pdf)
    a, b = _unmatched(candidates, 2)
    first, second = _free_products(client, session_id, candidates, 2)
    assert _confirm(client, session_id, a, first.row_number).status_code == 200
    assert _confirm(client, session_id, b, second.row_number).status_code == 200
    ids = {m["supplier_name_raw"]: m["id"] for m in _saved(client)}

    taken = client.put(
        f"/api/suppliers/azin_pipe/mappings/{ids[b['supplier_name']]}",
        json={"pioneers_name_raw": first.name, "pioneers_code": first.code},
    )
    assert taken.status_code == 409, taken.text
    assert taken.json()["detail"]["conflicts"][0]["supplier_name"] == a["supplier_name"]
    unchanged = client.put(
        f"/api/suppliers/azin_pipe/mappings/{ids[b['supplier_name']]}",
        json={"pioneers_name_raw": second.name, "pioneers_code": second.code},
    )
    assert unchanged.status_code == 200, unchanged.text
    # Typing the product's name without its code is still the same product.
    by_name = client.put(
        f"/api/suppliers/azin_pipe/mappings/{ids[b['supplier_name']]}",
        json={"pioneers_name_raw": f"  {first.name} ", "pioneers_code": None},
    )
    assert by_name.status_code == 409, by_name.text
    # Same name, different codes: two distinct Pioneers products, no conflict.
    same_name_other_code = client.put(
        f"/api/suppliers/azin_pipe/mappings/{ids[b['supplier_name']]}",
        json={"pioneers_name_raw": first.name, "pioneers_code": "99999"},
    )
    assert same_name_other_code.status_code == 200, same_name_other_code.text


def test_other_suppliers_are_not_blocked(client, pioneers_azin_excel: Path, azin_pdf: Path) -> None:
    session_id, candidates = _session(client, pioneers_azin_excel, azin_pdf)
    a = _unmatched(candidates, 1)[0]
    (target,) = _free_products(client, session_id, candidates, 1)
    database = client.app.state.database
    with database.session() as sess:
        dina = SupplierRepository(sess).create(name="دینا پلیمر", parser_type="dina_polymer")
        MappingRepository(sess).create(
            supplier_id=dina.id,
            supplier_name_raw="لوله دینا",
            pioneers_name_raw=target.name,
            pioneers_code=target.code,
        )
    assert _confirm(client, session_id, a, target.row_number).status_code == 200


def test_product_search_marks_products_held_by_another_supplier_product(
    client, pioneers_azin_excel: Path, azin_pdf: Path
) -> None:
    session_id, candidates = _session(client, pioneers_azin_excel, azin_pdf)
    a, b = _unmatched(candidates, 2)
    (target,) = _free_products(client, session_id, candidates, 1)
    assert _confirm(client, session_id, a, target.row_number).status_code == 200

    def assigned(candidate_id: str) -> str | None:
        found = client.get(
            f"/api/sessions/{session_id}/pioneers-products/search",
            params={"q": target.code, "candidate_id": candidate_id},
        ).json()["results"]
        return next(r for r in found if r["row_number"] == target.row_number)["assigned_to"]

    assert assigned(b["candidate_id"]) == a["supplier_name"]
    assert assigned(a["candidate_id"]) is None  # its own target is not "taken"


def test_concurrent_requests_cannot_both_claim_one_product(
    client, pioneers_azin_excel: Path, azin_pdf: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first_session, first_rows = _session(client, pioneers_azin_excel, azin_pdf)
    second_session, second_rows = _session(client, pioneers_azin_excel, azin_pdf)
    a = _unmatched(first_rows, 1)[0]
    b = next(c for c in _unmatched(second_rows, 2) if c["supplier_name"] != a["supplier_name"])
    (target,) = _free_products(client, first_session, first_rows, 1)

    original = mapping_repository.MappingRepository.upsert

    def slow_upsert(self, **kwargs):
        time.sleep(0.3)  # widen the check-then-write window
        return original(self, **kwargs)

    monkeypatch.setattr(mapping_repository.MappingRepository, "upsert", slow_upsert)
    service = client.app.state.processing
    database = client.app.state.database
    barrier = threading.Barrier(2)
    outcomes: list[str] = []

    def claim(session_id: str, candidate: dict) -> None:
        with database.session() as sess:
            barrier.wait()
            try:
                service.confirm_mapping(
                    session_id,
                    sess,
                    candidate_id=candidate["candidate_id"],
                    pioneers_row_number=target.row_number,
                    save=True,
                )
                outcomes.append("saved")
            except DuplicateMappingTargetError:
                outcomes.append("rejected")

    threads = [
        threading.Thread(target=claim, args=(first_session, a)),
        threading.Thread(target=claim, args=(second_session, b)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    assert sorted(outcomes) == ["rejected", "saved"]
    holders = [m for m in _saved(client) if m["pioneers_code"] == target.code]
    assert len(holders) == 1


def _product(row: int, name: str, code: str) -> PioneersProduct:
    return PioneersProduct(row_number=row, code=code, name=name, sale_price=Decimal("1000"))


def _item(name: str, code: str) -> SupplierPriceItem:
    return SupplierPriceItem(
        supplier_id="azin_pipe", supplier_code=code, supplier_name=name, price=Decimal("2000")
    )


def test_automatic_matching_keeps_one_holder_per_pioneers_product() -> None:
    processor = AzinPipeProcessor()
    products = [_product(2, "اذین لوله 20", "11489"), _product(3, "اذین لوله 25", "11490")]
    saved_item = _item("اذین لوله تک لایه 20", "S1")
    exact_item = _item("اذین لوله 20", "S2")
    saved = SavedNameMapping(
        supplier_name_normalized=processor.normalize_supplier_name(saved_item.supplier_name),
        pioneers_name_raw="اذین لوله 20",
        pioneers_name_normalized=normalize_product_name("اذین لوله 20"),
        pioneers_code="11489",
        identity_key=supplier_product_identity(
            normalized_name=processor.normalize_supplier_name(saved_item.supplier_name),
            supplier_code="S1",
            unit=None,
        ),
        supplier_code="S1",
    )

    result = match_supplier_items(
        [saved_item, exact_item], products, processor=processor, saved_mappings=[saved]
    )

    by_code = {c.supplier_code: c for c in result.candidates}
    # The saved decision wins over the exact name; the exact name is flagged.
    assert by_code["S1"].status is MatchStatus.MATCHED
    assert by_code["S1"].pioneers_code == "11489"
    assert by_code["S2"].status is MatchStatus.AMBIGUOUS
    assert DUPLICATE_TARGET_WARNING in by_code["S2"].warnings
    assert by_code["S2"].suggestions[0]["held_by"] == ["اذین لوله تک لایه 20"]
    assert (result.matched_count, result.ambiguous_count) == (1, 1)


def test_dialog_suggestions_mark_products_held_right_now(
    client, pioneers_azin_excel: Path, azin_pdf: Path
) -> None:
    session_id, candidates = _session(client, pioneers_azin_excel, azin_pdf)
    holders = {
        c["row_number"]: c["supplier_name"] for c in candidates if c["status"] == "MATCHED"
    }
    row = next(
        c
        for c in candidates
        if c["status"] == "AMBIGUOUS"
        and any(s["row_number"] in holders for s in c["suggestions"])
        and any(s["row_number"] not in holders for s in c["suggestions"])
    )

    def suggestions(candidate_id: str) -> list[dict]:
        response = client.get(
            f"/api/sessions/{session_id}/candidates/{candidate_id}/suggestions"
        )
        assert response.status_code == 200, response.text
        return response.json()["suggestions"]

    listed = suggestions(row["candidate_id"])
    assert [s["row_number"] for s in listed] == [s["row_number"] for s in row["suggestions"]]
    for suggestion in listed:
        assert suggestion["assigned_to"] == holders.get(suggestion["row_number"])

    # Held is computed now: once a free suggestion is taken, it is marked too.
    free = next(s for s in listed if s["assigned_to"] is None)
    other = next(
        c for c in _unmatched(candidates, 3) if c["candidate_id"] != row["candidate_id"]
    )
    assert _confirm(client, session_id, other, free["row_number"]).status_code == 200
    again = {s["row_number"]: s["assigned_to"] for s in suggestions(row["candidate_id"])}
    assert again[free["row_number"]] == other["supplier_name"]

    missing = client.get(f"/api/sessions/{session_id}/candidates/nope/suggestions")
    assert missing.status_code == 404
