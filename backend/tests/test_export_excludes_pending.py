"""Regression: excluded candidates must not appear in the exported workbook."""

from __future__ import annotations

from pathlib import Path

from openpyxl import load_workbook


def test_excluded_row_not_updated_in_download(
    client, pioneers_azin_excel: Path, azin_pdf: Path, tmp_path: Path
) -> None:
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
    client.post(f"/api/sessions/{session_id}/match")

    preview = client.get(f"/api/sessions/{session_id}/preview").json()["candidates"]
    matched = [c for c in preview if c["status"] == "MATCHED"]
    assert len(matched) >= 2

    keep, drop = matched[0], matched[1]
    client.post(
        f"/api/sessions/{session_id}/candidates/{keep['candidate_id']}/review",
        json={"decision": "APPROVE"},
    )
    client.post(
        f"/api/sessions/{session_id}/candidates/{drop['candidate_id']}/review",
        json={"decision": "EXCLUDE"},
    )
    for c in matched[2:]:
        client.post(
            f"/api/sessions/{session_id}/candidates/{c['candidate_id']}/review",
            json={"decision": "EXCLUDE"},
        )

    export = client.post(f"/api/sessions/{session_id}/export")
    assert export.status_code == 200
    assert export.json()["updated_count"] == 1

    download = client.get(f"/api/sessions/{session_id}/download")
    assert download.status_code == 200
    out = tmp_path / "out.xlsx"
    out.write_bytes(download.content)

    wb = load_workbook(out, read_only=True, data_only=True)
    ws = wb.active
    headers = [c.value for c in next(ws.iter_rows(min_row=1, max_row=1))]
    sale_idx = headers.index("نرخ فروش اصلی")

    keep_row = [
        c.value
        for c in next(ws.iter_rows(min_row=keep["row_number"], max_row=keep["row_number"]))
    ]
    assert str(keep_row[sale_idx]).replace(",", "") == str(keep["new_price"]).replace(
        ",", ""
    )

    # Excluded row must keep the old price from the original workbook semantics:
    # writer only patches exportable rows, so old_price remains.
    drop_row = [
        c.value
        for c in next(ws.iter_rows(min_row=drop["row_number"], max_row=drop["row_number"]))
    ]
    assert str(drop_row[sale_idx]).replace(",", "") == str(drop["old_price"]).replace(
        ",", ""
    )
    wb.close()

    # Original fixture untouched
    assert pioneers_azin_excel.stat().st_size > 0
