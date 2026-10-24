"""API success/error scenarios and end-to-end session workflow."""

from __future__ import annotations

import hashlib
import subprocess
import sys
from decimal import Decimal
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_list_suppliers(client) -> None:
    response = client.get("/api/suppliers")
    assert response.status_code == 200
    body = response.json()
    assert any(s["key"] == "azin_pipe" for s in body)


def test_settings_round_trip(client) -> None:
    get_resp = client.get("/api/settings")
    assert get_resp.status_code == 200
    assert "suspicious_percent_threshold" in get_resp.json()["settings"]

    put_resp = client.put(
        "/api/settings",
        json={"settings": {"suspicious_percent_threshold": "25"}},
    )
    assert put_resp.status_code == 200
    assert put_resp.json()["settings"]["suspicious_percent_threshold"] == "25"

    bad = client.put("/api/settings", json={"settings": {"unknown": "1"}})
    assert bad.status_code == 400


def test_unsupported_supplier_pdf(client, tmp_path: Path, azin_pdf: Path) -> None:
    session_id = client.post("/api/sessions").json()["session_id"]
    with azin_pdf.open("rb") as handle:
        response = client.post(
            f"/api/sessions/{session_id}/supplier-pdf",
            data={"supplier_key": "not_a_real_supplier"},
            files={"file": ("x.pdf", handle, "application/pdf")},
        )
    assert response.status_code == 400
    assert "Unsupported supplier" in response.json()["detail"]


def test_session_not_found(client) -> None:
    response = client.get("/api/sessions/does-not-exist")
    assert response.status_code == 404


@pytest.mark.parametrize("extension", ["xlsx", "xls"])
def test_end_to_end_azin_workflow(
    client, pioneers_azin_excel: Path, azin_pdf: Path, tmp_path: Path,
    extension: str,
) -> None:
    pioneers_azin_excel = pioneers_azin_excel.with_suffix(f".{extension}")
    source_sha = hashlib.sha256(pioneers_azin_excel.read_bytes()).hexdigest()
    # 1) create session
    session_id = client.post("/api/sessions").json()["session_id"]

    # 2) upload pioneers excel
    with pioneers_azin_excel.open("rb") as handle:
        excel_resp = client.post(
            f"/api/sessions/{session_id}/pioneers-excel",
            files={
                "file": (
                    pioneers_azin_excel.name,
                    handle,
                    "application/vnd.ms-excel" if extension == "xls" else
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
            },
        )
    assert excel_resp.status_code == 200, excel_resp.text
    assert excel_resp.json()["product_count"] > 0

    # 3) upload azin pdf
    with azin_pdf.open("rb") as handle:
        pdf_resp = client.post(
            f"/api/sessions/{session_id}/supplier-pdf",
            data={"supplier_key": "azin_pipe"},
            files={"file": ("azin.pdf", handle, "application/pdf")},
        )
    assert pdf_resp.status_code == 200, pdf_resp.text
    assert pdf_resp.json()["supplier_item_count"] >= 200

    # 4) match
    match_resp = client.post(
        f"/api/sessions/{session_id}/match",
        json={"suspicious_percent_threshold": "30"},
    )
    assert match_resp.status_code == 200, match_resp.text
    payload = match_resp.json()
    assert (
        payload["matched_count"]
        + payload["unmatched_count"]
        + payload["ambiguous_count"]
        + payload["ignored_count"]
        == len(payload["candidates"])
    )

    # Confirmed printed Rial: no generic listed-basis blocker. Soft suspicious-%
    # warnings still need APPROVE; only نرخ فروش اصلی may change on export.
    keep = next(row for row in payload["candidates"] if row["supplier_code"] == "819121025")
    assert keep["status"] == "MATCHED"
    assert keep["source_currency"] == "rial"
    assert keep["price_basis"] == "printed"
    assert keep["pricing_blockers"] == []
    assert keep["exportable"] is False
    assert Decimal(keep["new_price"]) > 0
    assert Decimal(keep["new_price"]) != Decimal(keep["old_price"])
    assert keep["row_number"] > 2  # The approved-only export compacts this to row 2.
    confirmed = client.post(
        f"/api/sessions/{session_id}/candidates/{keep['candidate_id']}/confirm-mapping",
        json={"pioneers_row_number": keep["row_number"], "save": True},
    )
    assert confirmed.status_code == 200, confirmed.text
    before_approval = client.post(f"/api/sessions/{session_id}/export")
    assert before_approval.status_code == 400, before_approval.text
    review = client.post(
        f"/api/sessions/{session_id}/candidates/{keep['candidate_id']}/review",
        json={"decision": "APPROVE"},
    )
    assert review.status_code == 200, review.text
    assert review.json()["exportable"] is True
    assert review.json()["review_decision"] == "APPROVE"
    assert review.json()["pricing_blockers"] == []
    for row in payload["candidates"]:
        if row["candidate_id"] == keep["candidate_id"]:
            continue
        excluded = client.post(
            f"/api/sessions/{session_id}/candidates/{row['candidate_id']}/review",
            json={"decision": "EXCLUDE"},
        )
        assert excluded.status_code == 200, excluded.text
    export_resp = client.post(f"/api/sessions/{session_id}/export")
    assert export_resp.status_code == 200, export_resp.text
    assert export_resp.json()["updated_count"] == 1
    assert export_resp.json()["exported_row_count"] == 1
    download = client.get(f"/api/sessions/{session_id}/download")
    assert download.status_code == 200, download.text
    exported = tmp_path / "export.xlsx"
    exported.write_bytes(download.content)
    # Exercise the same CLIs used by the packaged smoke, including HTML-XLS
    # conversion, source immutability, approved identity/count, and exact price.
    comparison = [
        sys.executable, str(REPO_ROOT / "scripts/windows/compare_export.py"),
        "--source", str(pioneers_azin_excel), "--exported", str(exported),
        "--source-sha256", source_sha,
    ]
    if extension == "xls":
        comparison.append("--html-xls")
    subprocess.run(comparison, check=True)
    subprocess.run([
        sys.executable, str(REPO_ROOT / "scripts/windows/check_export_price.py"),
        "--exported", str(exported), "--code", keep["pioneers_code"],
        "--price", review.json()["new_price"],
    ], check=True)
    assert hashlib.sha256(pioneers_azin_excel.read_bytes()).hexdigest() == source_sha


def test_search_pioneers_products(client, pioneers_azin_excel: Path) -> None:
    session_id = client.post("/api/sessions").json()["session_id"]
    with pioneers_azin_excel.open("rb") as handle:
        client.post(
            f"/api/sessions/{session_id}/pioneers-excel",
            files={"file": ("p.xlsx", handle, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        )
    response = client.get(
        f"/api/sessions/{session_id}/pioneers-products/search",
        params={"q": "اذین بوشن"},
    )
    assert response.status_code == 200
    assert len(response.json()["results"]) >= 1
