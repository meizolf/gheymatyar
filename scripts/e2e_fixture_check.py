#!/usr/bin/env python3
"""End-to-end API check against real fixtures (no browser).

Azin prices stay blocked until their source basis is an explicit metre or piece
price. A separate Dina per-metre row is exported only after Rial per-metre is
confirmed, and only that sale cell may change.
"""

from __future__ import annotations

import sys
import tempfile
from decimal import Decimal
from pathlib import Path

from fastapi.testclient import TestClient
from openpyxl import load_workbook

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend" / "src"))

from gheymatyar.main import create_app  # noqa: E402
from gheymatyar.parsers.pioneers_excel_parser import HEADER_SALE_PRICE  # noqa: E402

EXCEL = ROOT / "fixtures" / "pioneers" / "pioneers_azin_subset.xlsx"
AZIN_PDF = ROOT / "fixtures" / "suppliers" / "458_124550609784457.pdf"
DINA_PDF = ROOT / "fixtures" / "suppliers" / "dina_polymer_1405_07_04.pdf"


def _upload(client: TestClient, session_id: str, excel: Path, pdf: Path, supplier_key: str) -> None:
    with excel.open("rb") as handle:
        excel_resp = client.post(
            f"/api/sessions/{session_id}/pioneers-excel",
            files={
                "file": (
                    "p.xlsx",
                    handle,
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
            },
        )
    assert excel_resp.status_code == 200, excel_resp.text
    with pdf.open("rb") as handle:
        pdf_resp = client.post(
            f"/api/sessions/{session_id}/supplier-pdf",
            data={"supplier_key": supplier_key},
            files={"file": ("list.pdf", handle, "application/pdf")},
        )
    assert pdf_resp.status_code == 200, pdf_resp.text


def _assert_azin_export_rejected(client: TestClient) -> None:
    session_id = client.post("/api/sessions").json()["session_id"]
    _upload(client, session_id, EXCEL, AZIN_PDF, "azin_pipe")
    match = client.post(f"/api/sessions/{session_id}/match")
    assert match.status_code == 200, match.text
    preview = client.get(f"/api/sessions/{session_id}/preview").json()["candidates"]
    matched = [row for row in preview if row["status"] == "MATCHED"]
    assert matched, "expected a matched Azin row"
    assert all(row["exportable"] is False for row in matched)
    approved = client.post(
        f"/api/sessions/{session_id}/candidates/{matched[0]['candidate_id']}/review",
        json={"decision": "APPROVE"},
    )
    assert approved.status_code == 400, approved.text
    exported = client.post(f"/api/sessions/{session_id}/export")
    assert exported.status_code == 400, exported.text
    download = client.get(f"/api/sessions/{session_id}/download")
    assert download.status_code == 404
    print("Azin unresolved export rejected")


def _sale_cell(path: Path, row_number: int):
    workbook = load_workbook(path, data_only=False)
    try:
        sheet = workbook.active
        headers = {cell.value: cell.column for cell in sheet[1]}
        return sheet.cell(row_number, headers[HEADER_SALE_PRICE]).value
    finally:
        workbook.close()


def _assert_dina_metre_export(client: TestClient, work_dir: Path) -> None:
    settings = client.put(
        "/api/settings",
        json={
            "settings": {
                "pioneers_sale_currency": "rial",
                "pioneers_sale_basis": "meter",
            }
        },
    )
    assert settings.status_code == 200, settings.text

    session_id = client.post("/api/sessions").json()["session_id"]
    _upload(client, session_id, EXCEL, DINA_PDF, "dina_polymer")
    match = client.post(f"/api/sessions/{session_id}/match")
    assert match.status_code == 200, match.text
    candidates = client.get(f"/api/sessions/{session_id}/candidates").json()["candidates"]
    pipe = next(
        row
        for row in candidates
        if row.get("price_basis") == "meter" and not row.get("pricing_blockers")
    )
    search = client.get(
        f"/api/sessions/{session_id}/pioneers-products/search",
        params={"q": "لوله"},
    )
    assert search.status_code == 200, search.text
    row_number = int(search.json()["results"][0]["row_number"])
    confirmed = client.post(
        f"/api/sessions/{session_id}/candidates/{pipe['candidate_id']}/confirm-mapping",
        json={"pioneers_row_number": row_number, "save": True},
    )
    assert confirmed.status_code == 200, confirmed.text
    body = confirmed.json()
    assert not body["pricing_blockers"], body["pricing_blockers"]
    assert body["new_price"] == pipe["new_price"]
    if not body["exportable"]:
        approved = client.post(
            f"/api/sessions/{session_id}/candidates/{pipe['candidate_id']}/review",
            json={"decision": "APPROVE"},
        )
        assert approved.status_code == 200, approved.text
        body = approved.json()
        assert body["exportable"] is True
        assert not body["pricing_blockers"]

    for row in candidates:
        if row["candidate_id"] == pipe["candidate_id"]:
            continue
        excluded = client.post(
            f"/api/sessions/{session_id}/candidates/{row['candidate_id']}/review",
            json={"decision": "EXCLUDE"},
        )
        assert excluded.status_code == 200, excluded.text

    exported = client.post(f"/api/sessions/{session_id}/export")
    assert exported.status_code == 200, exported.text
    assert exported.json()["updated_count"] >= 1
    download = client.get(f"/api/sessions/{session_id}/download")
    assert download.status_code == 200
    assert len(download.content) > 1000
    output = work_dir / "dina_export.xlsx"
    output.write_bytes(download.content)
    written = _sale_cell(output, row_number)
    assert Decimal(str(written)) == Decimal(body["new_price"])
    original = _sale_cell(EXCEL, row_number)
    assert Decimal(str(written)) != Decimal(str(original))

    mappings = client.get("/api/suppliers/dina_polymer/mappings")
    assert mappings.status_code == 200, mappings.text
    assert mappings.json()["mappings"], "expected the confirmed Dina mapping to be saved"
    print(
        f"Dina metre export wrote {body['new_price']} on row {row_number} "
        f"({exported.json()['updated_count']} updates)"
    )


def main() -> int:
    missing = [path for path in (EXCEL, AZIN_PDF, DINA_PDF) if not path.is_file()]
    if missing:
        print("missing fixtures: " + ", ".join(str(path) for path in missing), file=sys.stderr)
        return 1

    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "e2e.db"
        app = create_app(database_url=f"sqlite:///{db}", mount_spa=False)
        with TestClient(app) as client:
            assert client.get("/api/health").json()["status"] == "ok"
            suppliers = client.get("/api/suppliers").json()
            assert any(item["key"] == "azin_pipe" for item in suppliers)
            assert any(item["key"] == "dina_polymer" for item in suppliers)
            _assert_azin_export_rejected(client)
            _assert_dina_metre_export(client, Path(tmp))
            print("E2E fixture workflow OK")
            return 0


if __name__ == "__main__":
    raise SystemExit(main())
