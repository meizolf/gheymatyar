"""Saved mapping CRUD API tests."""

from __future__ import annotations

from pathlib import Path

from gheymatyar.domain.enums import MappingType
from gheymatyar.repositories.mapping_repository import MappingRepository
from gheymatyar.repositories.supplier_repository import SupplierRepository


def test_list_mappings_empty_for_known_supplier(client) -> None:
    response = client.get("/api/suppliers/azin_pipe/mappings")
    assert response.status_code == 200
    body = response.json()
    assert body["supplier_key"] == "azin_pipe"
    assert body["mappings"] == []


def test_list_mappings_unknown_supplier(client) -> None:
    response = client.get("/api/suppliers/not_real/mappings")
    assert response.status_code == 404


def test_mapping_update_and_delete(
    client, pioneers_azin_excel: Path, azin_pdf: Path
) -> None:
    # Seed a mapping via the session confirm flow after match
    session_id = client.post("/api/sessions").json()["session_id"]
    with pioneers_azin_excel.open("rb") as handle:
        client.post(
            f"/api/sessions/{session_id}/pioneers-excel",
            files={
                "file": (
                    "p.xlsx",
                    handle,
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
            },
        )
    with azin_pdf.open("rb") as handle:
        client.post(
            f"/api/sessions/{session_id}/supplier-pdf",
            data={"supplier_key": "azin_pipe"},
            files={"file": ("azin.pdf", handle, "application/pdf")},
        )
    match = client.post(f"/api/sessions/{session_id}/match").json()
    # A Pioneers product already matched to another supplier product is taken.
    taken = {c["row_number"] for c in match["candidates"] if c["status"] == "MATCHED"}
    needy = next(
        (
            c
            for c in match["candidates"]
            if c["status"] in {"UNMATCHED", "AMBIGUOUS"}
            and any(s["row_number"] not in taken for s in c["suggestions"])
        ),
        None,
    )
    if needy is not None:
        suggestion = next(s for s in needy["suggestions"] if s["row_number"] not in taken)
        confirm = client.post(
            f"/api/sessions/{session_id}/candidates/{needy['candidate_id']}/confirm-mapping",
            json={"pioneers_row_number": suggestion["row_number"], "save": True},
        )
        assert confirm.status_code == 200, confirm.text
    else:
        # Seed via the same DB the API client uses
        database = client.app.state.database
        with database.session() as sess:
            supplier = SupplierRepository(sess).create(
                name="آذین لوله", parser_type="azin_pipe"
            )
            MappingRepository(sess).create(
                supplier_id=supplier.id,
                supplier_name_raw="تست محصول",
                pioneers_name_raw="محصول پایونیرز",
                pioneers_code="999",
                mapping_type=MappingType.MANUAL,
            )

    listed = client.get("/api/suppliers/azin_pipe/mappings")
    assert listed.status_code == 200
    mappings = listed.json()["mappings"]
    assert len(mappings) >= 1
    mapping = mappings[0]
    mid = mapping["id"]

    updated = client.put(
        f"/api/suppliers/azin_pipe/mappings/{mid}",
        json={"pioneers_name_raw": "نام اصلاح‌شده", "pioneers_code": "42"},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["pioneers_name_raw"] == "نام اصلاح‌شده"
    assert updated.json()["pioneers_code"] == "42"
    assert updated.json()["mapping_type"] == "MANUAL"

    deleted = client.delete(f"/api/suppliers/azin_pipe/mappings/{mid}")
    assert deleted.status_code == 204

    after = client.get("/api/suppliers/azin_pipe/mappings")
    assert all(m["id"] != mid for m in after.json()["mappings"])


def test_mapping_update_distinguishes_omitted_code_from_null(client) -> None:
    database = client.app.state.database
    with database.session() as sess:
        supplier = SupplierRepository(sess).create(
            name="آذین لوله", parser_type="azin_pipe"
        )
        MappingRepository(sess).create(
            supplier_id=supplier.id,
            supplier_name_raw="کالای مشترک 20",
            supplier_code="VARIANT-A",
            pioneers_name_raw="هدف",
            pioneers_code="111",
            mapping_type=MappingType.MANUAL,
        )
        MappingRepository(sess).create(
            supplier_id=supplier.id,
            supplier_name_raw="کالای مشترک 20",
            supplier_code="VARIANT-B",
            pioneers_name_raw="هدف دیگر",
            pioneers_code="222",
            mapping_type=MappingType.MANUAL,
        )

    listed = client.get("/api/suppliers/azin_pipe/mappings")
    assert listed.status_code == 200
    rows = {row["supplier_code"]: row for row in listed.json()["mappings"]}
    omitted = client.put(
        f"/api/suppliers/azin_pipe/mappings/{rows['VARIANT-A']['id']}",
        json={"pioneers_name_raw": "هدف"},
    )
    assert omitted.status_code == 200, omitted.text
    assert omitted.json()["pioneers_code"] == "111"

    cleared = client.put(
        f"/api/suppliers/azin_pipe/mappings/{rows['VARIANT-A']['id']}",
        json={"pioneers_name_raw": "بی‌کد", "pioneers_code": None},
    )
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["pioneers_code"] is None

    untouched = client.get("/api/suppliers/azin_pipe/mappings").json()["mappings"]
    other = next(row for row in untouched if row["supplier_code"] == "VARIANT-B")
    assert other["pioneers_code"] == "222"


def test_delete_missing_mapping(client) -> None:
    response = client.delete("/api/suppliers/azin_pipe/mappings/999999")
    assert response.status_code == 404
