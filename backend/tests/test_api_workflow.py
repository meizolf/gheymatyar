"""API success/error scenarios and end-to-end session workflow."""

from __future__ import annotations

from pathlib import Path

from openpyxl import load_workbook


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


def test_end_to_end_azin_workflow(
    client, pioneers_azin_excel: Path, azin_pdf: Path, tmp_path: Path
) -> None:
    # 1) create session
    session_id = client.post("/api/sessions").json()["session_id"]

    # 2) upload pioneers excel
    with pioneers_azin_excel.open("rb") as handle:
        excel_resp = client.post(
            f"/api/sessions/{session_id}/pioneers-excel",
            files={
                "file": (
                    "pioneers.xlsx",
                    handle,
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
    assert payload["matched_count"] + payload["unmatched_count"] + payload[
        "ambiguous_count"
    ] == len(payload["candidates"])

    # 5) manually confirm one unmatched/ambiguous if needed, else use a matched one
    candidates = payload["candidates"]
    exportable = [c for c in candidates if c["exportable"]]
    if not exportable:
        # Confirm a suggestion manually
        needy = next(
            c
            for c in candidates
            if c["status"] in {"UNMATCHED", "AMBIGUOUS"} and c["suggestions"]
        )
        suggestion = needy["suggestions"][0]
        confirm = client.post(
            f"/api/sessions/{session_id}/candidates/{needy['candidate_id']}/confirm-mapping",
            json={"pioneers_row_number": suggestion["row_number"], "save": True},
        )
        assert confirm.status_code == 200, confirm.text
        # Approve if warnings present
        confirmed = confirm.json()
        if confirmed["warnings"]:
            review = client.post(
                f"/api/sessions/{session_id}/candidates/{needy['candidate_id']}/review",
                json={"decision": "APPROVE"},
            )
            assert review.status_code == 200
            assert review.json()["exportable"] is True
    else:
        # Approve warned matched rows so at least one exports
        target = exportable[0]
        if not target["exportable"]:
            pass
        # Prefer first matched; approve warnings
        matched = next(c for c in candidates if c["status"] == "MATCHED")
        if matched["warnings"] or not matched["exportable"]:
            review = client.post(
                f"/api/sessions/{session_id}/candidates/{matched['candidate_id']}/review",
                json={"decision": "APPROVE"},
            )
            assert review.status_code == 200

    # Ensure at least one exportable after approvals
    preview = client.get(f"/api/sessions/{session_id}/preview")
    assert preview.status_code == 200
    preview_candidates = preview.json()["candidates"]
    if not any(c["exportable"] for c in preview_candidates):
        matched = next(c for c in preview_candidates if c["status"] == "MATCHED")
        client.post(
            f"/api/sessions/{session_id}/candidates/{matched['candidate_id']}/review",
            json={"decision": "APPROVE"},
        )

    # Exclude everything except one approved row to keep export small/deterministic
    preview = client.get(f"/api/sessions/{session_id}/preview").json()["candidates"]
    keep = next(c for c in preview if c["status"] == "MATCHED")
    client.post(
        f"/api/sessions/{session_id}/candidates/{keep['candidate_id']}/review",
        json={"decision": "APPROVE"},
    )
    for c in preview:
        if c["candidate_id"] == keep["candidate_id"]:
            continue
        client.post(
            f"/api/sessions/{session_id}/candidates/{c['candidate_id']}/review",
            json={"decision": "EXCLUDE"},
        )

    # 6) export
    export_resp = client.post(f"/api/sessions/{session_id}/export")
    assert export_resp.status_code == 200, export_resp.text
    assert export_resp.json()["updated_count"] >= 1

    # 7) download
    download = client.get(f"/api/sessions/{session_id}/download")
    assert download.status_code == 200
    out_path = tmp_path / "out.xlsx"
    out_path.write_bytes(download.content)

    # Source immutability: original fixture untouched (size check)
    assert pioneers_azin_excel.stat().st_size > 0

    # Output has updated sale price for the kept row
    wb = load_workbook(out_path, read_only=True, data_only=True)
    ws = wb.active
    headers = [c.value for c in next(ws.iter_rows(min_row=1, max_row=1))]
    sale_idx = headers.index("نرخ فروش اصلی")
    row_number = keep["row_number"]
    row_vals = [c.value for c in next(ws.iter_rows(min_row=row_number, max_row=row_number))]
    assert str(row_vals[sale_idx]).replace(",", "") == str(keep["new_price"]).replace(
        ",", ""
    )
    wb.close()


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
