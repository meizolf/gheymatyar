"""Saved mappings export to one JSON file and import safely elsewhere.

Two app instances on separate SQLite files stand in for two computers.
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path

from fastapi.testclient import TestClient

from gheymatyar.main import create_app
from gheymatyar.db import Database
from gheymatyar.domain.enums import MatchStatus
from gheymatyar.domain.product import PioneersProduct
from gheymatyar.domain.supplier_item import SupplierPriceItem
from gheymatyar.repositories.mapping_repository import MappingRepository
from gheymatyar.services.mapping_transfer import _supplier_row
from gheymatyar.services.matching import SavedNameMapping, match_supplier_items
from gheymatyar.suppliers.registry import get_default_registry

# (supplier, supplier name, supplier code, Pioneers name, Pioneers code)
SEED = [
    ("texa", "تکسا شیر شوفاژ", "700", "شیر شوفاژ تکسا", "5001"),
    ("texa", "تکسا شیر و زانو شوفاژ", "700", "شیر و زانو شوفاژ تکسا", "5002"),
    # Same Pioneers product under another supplier: suppliers are isolated.
    ("azin_pipe", "اذین لوله تک لایه 20", "S1", "شیر شوفاژ تکسا", "5001"),
    ("azin_pipe", "اذین لوله تک لایه 25", None, "اذین لوله 25", None),
]


@contextmanager
def _install(path: Path):
    app = create_app(database_url=f"sqlite:///{path}", mount_spa=False)
    with TestClient(app) as client:
        yield client


def _seed(client, rows) -> None:
    with client.app.state.database.session() as db:
        for key, name, code, p_name, p_code in rows:
            supplier = _supplier_row(db, key, create=True)
            MappingRepository(db).create(
                supplier_id=supplier.id, supplier_name_raw=name,
                supplier_name_normalized=get_default_registry().get(key).normalize_supplier_name(name),
                supplier_code=code, pioneers_name_raw=p_name, pioneers_code=p_code,
            )


def _export(client) -> bytes:
    response = client.get("/api/mappings/export")
    assert response.status_code == 200
    assert 'filename="gheymatyar-mappings-' in response.headers["content-disposition"]
    return response.content


def _post(client, raw: bytes, *, apply: bool, replace=()):
    url = "/api/mappings/import" if apply else "/api/mappings/import/preview"
    data = {"replace": json.dumps(list(replace))} if apply else None
    return client.post(url, files={"file": ("m.json", raw, "application/json")}, data=data)


def _portable(raw: bytes) -> list[dict]:
    return [
        {k: v for k, v in m.items() if k not in {"created_at", "updated_at"}}
        for m in json.loads(raw)["mappings"]
    ]


def test_round_trip_is_isolated_by_supplier_and_idempotent(tmp_path: Path) -> None:
    with _install(tmp_path / "mac.db") as mac:
        _seed(mac, SEED)
        raw = _export(mac)
    document = json.loads(raw)
    assert (document["format"], document["schema_version"], document["mapping_count"]) == (
        "gheymatyar-mappings", 1, 4
    )
    assert not any({"id", "supplier_id", "row_number"} & set(m) for m in document["mappings"])

    with _install(tmp_path / "windows.db") as windows:
        preview = _post(windows, raw, apply=False).json()
        assert preview["counts"] == {"new": 4, "identical": 0, "conflict": 0, "invalid": 0, "replace": 0}
        assert _post(windows, raw, apply=True).json()["counts"]["new"] == 4
        assert _portable(_export(windows)) == _portable(raw)
        # The same file again: nothing new, nothing duplicated.
        again = _post(windows, raw, apply=True).json()
        assert again["counts"]["identical"] == 4 and again["counts"]["new"] == 0
        assert len(json.loads(_export(windows))["mappings"]) == 4


def test_conflicts_are_never_overwritten_without_a_choice(tmp_path: Path) -> None:
    with _install(tmp_path / "a.db") as source:
        _seed(source, SEED[:2])
        raw = _export(source)
    with _install(tmp_path / "b.db") as target:
        _seed(target, [
            # Same supplier product, another Pioneers product here.
            ("texa", "تکسا شیر شوفاژ", "700", "شیر شوفاژ قدیمی", "4001"),
            # Another supplier product already holds Pioneers 5002.
            ("texa", "تکسا زانو شوفاژ", "750", "شیر و زانو شوفاژ تکسا", "5002"),
        ])
        before = _portable(_export(target))
        plan = _post(target, raw, apply=False).json()
        by_name = {item["supplier_name"]: item for item in plan["items"]}
        elsewhere = by_name["تکسا شیر شوفاژ"]
        taken = by_name["تکسا شیر و زانو شوفاژ"]
        assert (elsewhere["reason"], elsewhere["existing_pioneers_code"], elsewhere["replaceable"]) == (
            "mapped_elsewhere", "4001", True
        )
        assert (taken["reason"], taken["holder"], taken["replaceable"]) == (
            "target_taken", "تکسا زانو شوفاژ", False
        )
        assert _post(target, raw, apply=True).json()["counts"]["conflict"] == 2
        assert _portable(_export(target)) == before  # nothing replaced silently

        # Replace only what the user picked; a taken product stays with its holder.
        chosen = [elsewhere["index"], taken["index"]]
        result = _post(target, raw, apply=True, replace=chosen).json()
        assert result["counts"]["replace"] == 1 and result["counts"]["conflict"] == 1
        codes = {m["supplier_name_raw"]: m["pioneers_code"] for m in json.loads(_export(target))["mappings"]}
        assert codes == {"تکسا شیر شوفاژ": "5001", "تکسا زانو شوفاژ": "5002"}


def test_invalid_files_and_records_change_nothing(tmp_path: Path) -> None:
    with _install(tmp_path / "c.db") as client:
        _seed(client, SEED[:1])
        before = _export(client)
        good = json.loads(before)
        bad_files = [
            b"not json",
            json.dumps({"format": "other", "schema_version": 1, "mappings": []}).encode(),
            json.dumps({**good, "schema_version": 2}).encode(),
            json.dumps({**good, "mappings": {}}).encode(),
        ]
        for raw in bad_files:
            for apply in (False, True):
                assert _post(client, raw, apply=apply).status_code == 400
        records = [
            {"supplier_key": "unknown_supplier", "supplier_name_raw": "x", "pioneers_name_raw": "y"},
            {"supplier_key": "texa", "supplier_name_raw": "", "pioneers_name_raw": "y"},
            "not an object",
        ]
        result = _post(client, json.dumps({**good, "mappings": records}).encode(), apply=True).json()
        assert result["counts"]["invalid"] == 3 and result["counts"]["new"] == 0
        assert _portable(_export(client)) == _portable(before)


def test_imported_mappings_survive_restart_and_are_revalidated(tmp_path: Path) -> None:
    with _install(tmp_path / "src.db") as source:
        _seed(source, SEED[:2])
        raw = _export(source)
    path = tmp_path / "restart.db"
    with _install(path) as client:
        assert _post(client, raw, apply=True).status_code == 200

    restarted = Database(f"sqlite:///{path}")
    with restarted.session() as db:
        rows = MappingRepository(db).list_for_supplier(_supplier_row(db, "texa", create=False).id)
    restarted.engine.dispose()
    saved = [
        SavedNameMapping(
            supplier_name_normalized=r.supplier_name_normalized, pioneers_name_raw=r.pioneers_name_raw,
            pioneers_name_normalized=r.pioneers_name_normalized, pioneers_code=r.pioneers_code,
            identity_key=r.identity_key, supplier_code=r.supplier_code,
            unit_normalized=r.unit_normalized, legacy_unscoped=r.legacy_unscoped,
        )
        for r in rows
    ]
    assert len(saved) == 2
    # This catalog has 5001 but not 5002: only the verified mapping is used.
    products = [PioneersProduct(row_number=2, code="5001", name="شیر شوفاژ تکسا",
                                sale_price=Decimal("1000"))]
    items = [SupplierPriceItem(supplier_id="texa", supplier_name=name, supplier_code="700",
                               price=Decimal("2000"))
             for name in ("تکسا شیر شوفاژ", "تکسا شیر و زانو شوفاژ")]
    result = match_supplier_items(items, products, processor=get_default_registry().get("texa"),
                                  saved_mappings=saved)
    status = {c.supplier_name: (c.status, c.pioneers_code) for c in result.candidates}
    assert status["تکسا شیر شوفاژ"] == (MatchStatus.MATCHED, "5001")
    assert status["تکسا شیر و زانو شوفاژ"][0] is not MatchStatus.MATCHED
