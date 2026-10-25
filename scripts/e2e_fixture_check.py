#!/usr/bin/env python3
"""End-to-end API check against real fixtures (no browser).

Azin printed prices are already Rial, so a matched row can be approved and
exported. Unmatched approval, and an export with nothing eligible, stay
rejected. A Dina per-metre row is exported at its printed Rial amount, and the
file contains only that approved product row.
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


def _assert_status(response, status: int) -> None:
    assert response.status_code == status, response.text


def _assert_azin_printed_rial_export(client: TestClient, work_dir: Path) -> None:
    session_id = client.post("/api/sessions").json()["session_id"]
    _upload(client, session_id, EXCEL, AZIN_PDF, "azin_pipe")
    _assert_status(client.post(f"/api/sessions/{session_id}/match"), 200)
    preview = client.get(f"/api/sessions/{session_id}/candidates").json()["candidates"]
    # A large printed-price move is a soft warning. Approval may override it.
    # A pricing blocker may not.
    eligible = [
        row
        for row in preview
        if row["status"] == "MATCHED"
        and not row.get("pricing_blockers")
        and row.get("new_price") not in {None, "", row.get("old_price")}
    ]
    assert eligible, "expected a matched Azin printed-Rial row"
    unmatched = next((row for row in preview if row["status"] == "UNMATCHED"), None)
    assert unmatched is not None, "expected an unmatched row for the restriction check"
    refused = client.post(
        f"/api/sessions/{session_id}/candidates/{unmatched['candidate_id']}/review",
        json={"decision": "APPROVE"},
    )
    _assert_status(refused, 400)

    target = eligible[0]
    approved = client.post(
        f"/api/sessions/{session_id}/candidates/{target['candidate_id']}/review",
        json={"decision": "APPROVE"},
    )
    _assert_status(approved, 200)
    assert approved.json()["exportable"] is True
    assert not approved.json()["pricing_blockers"]

    for row in preview:
        if row["candidate_id"] == target["candidate_id"]:
            continue
        excluded = client.post(
            f"/api/sessions/{session_id}/candidates/{row['candidate_id']}/review",
            json={"decision": "EXCLUDE"},
        )
        _assert_status(excluded, 200)

    exported = client.post(f"/api/sessions/{session_id}/export")
    _assert_status(exported, 200)
    assert exported.json()["updated_count"] == 1
    assert exported.json()["exported_row_count"] == 1
    download = client.get(f"/api/sessions/{session_id}/download?format=xlsx")
    _assert_status(download, 200)
    output = work_dir / "azin_export.xlsx"
    output.write_bytes(download.content)
    written = _sale_cell_for_code(output, target["pioneers_code"])
    assert Decimal(str(written)) == Decimal(approved.json()["new_price"])
    original_book = load_workbook(EXCEL, data_only=False)
    exported_book = load_workbook(output, data_only=False)
    try:
        original_sheet = original_book.active
        exported_sheet = exported_book.active
        assert exported_sheet.max_row == 2
        headers = {cell.value: cell.column for cell in original_sheet[1]}
        sale_column = headers[HEADER_SALE_PRICE]
        code_column = headers["کد کالا"]
        source_row = int(target["row_number"])
        for column in range(1, original_sheet.max_column + 1):
            source_value = original_sheet.cell(source_row, column).value
            exported_value = exported_sheet.cell(2, column).value
            if column == sale_column:
                assert exported_value != source_value
                continue
            assert exported_value == source_value
        assert exported_sheet.cell(2, code_column).value == target["pioneers_code"]
    finally:
        original_book.close()
        exported_book.close()

    blocked = client.post("/api/sessions").json()["session_id"]
    _upload(client, blocked, EXCEL, AZIN_PDF, "azin_pipe")
    _assert_status(client.post(f"/api/sessions/{blocked}/match"), 200)
    blocked_rows = client.get(f"/api/sessions/{blocked}/candidates").json()["candidates"]
    for row in blocked_rows:
        excluded = client.post(
            f"/api/sessions/{blocked}/candidates/{row['candidate_id']}/review",
            json={"decision": "EXCLUDE"},
        )
        _assert_status(excluded, 200)
    rejected = client.post(f"/api/sessions/{blocked}/export")
    _assert_status(rejected, 400)
    assert client.get(f"/api/sessions/{blocked}/download").status_code == 404
    print("Azin printed-Rial export wrote one sale cell; empty export rejected")


def _sale_cell_for_code(path: Path, pioneers_code: str):
    workbook = load_workbook(path, data_only=False)
    try:
        sheet = workbook.active
        headers = {cell.value: cell.column for cell in sheet[1]}
        code_column = headers["کد کالا"]
        sale_column = headers[HEADER_SALE_PRICE]
        for row in range(2, (sheet.max_row or 1) + 1):
            if sheet.cell(row, code_column).value == pioneers_code:
                return sheet.cell(row, sale_column).value
        raise AssertionError(f"exported file is missing code {pioneers_code}")
    finally:
        workbook.close()


def _assert_dina_metre_export(client: TestClient, work_dir: Path) -> None:
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
    assert exported.json()["exported_row_count"] == exported.json()["updated_count"]
    download = client.get(f"/api/sessions/{session_id}/download?format=xlsx")
    assert download.status_code == 200
    assert len(download.content) > 1000
    output = work_dir / "dina_export.xlsx"
    output.write_bytes(download.content)
    written = _sale_cell_for_code(output, body["pioneers_code"])
    assert Decimal(str(written)) == Decimal(body["new_price"])
    original_book = load_workbook(EXCEL, data_only=False)
    try:
        sheet = original_book.active
        headers = {cell.value: cell.column for cell in sheet[1]}
        original = sheet.cell(row_number, headers[HEADER_SALE_PRICE]).value
    finally:
        original_book.close()
    assert Decimal(str(written)) != Decimal(str(original))
    exported_book = load_workbook(output, data_only=False)
    try:
        assert exported_book.active.max_row == 1 + int(exported.json()["exported_row_count"])
    finally:
        exported_book.close()

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
            _assert_azin_printed_rial_export(client, Path(tmp))
            _assert_dina_metre_export(client, Path(tmp))
            print("E2E fixture workflow OK")
            return 0


if __name__ == "__main__":
    raise SystemExit(main())
