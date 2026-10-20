"""Per-session locks: explicit ordered concurrency scenarios for review vs export."""

from __future__ import annotations

from pathlib import Path

from openpyxl import load_workbook


def _prepare_two_exportable(
    client, pioneers_azin_excel: Path, azin_pdf: Path
) -> tuple[str, dict, dict]:
    session_id = client.post("/api/sessions").json()["session_id"]
    with pioneers_azin_excel.open("rb") as handle:
        assert (
            client.post(
                f"/api/sessions/{session_id}/pioneers-excel",
                files={
                    "file": (
                        "p.xlsx",
                        handle,
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    )
                },
            ).status_code
            == 200
        )
    with azin_pdf.open("rb") as handle:
        assert (
            client.post(
                f"/api/sessions/{session_id}/supplier-pdf",
                data={"supplier_key": "azin_pipe"},
                files={"file": ("azin.pdf", handle, "application/pdf")},
            ).status_code
            == 200
        )
    assert client.post(f"/api/sessions/{session_id}/match").status_code == 200

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
        json={"decision": "APPROVE"},
    )
    for c in matched[2:]:
        client.post(
            f"/api/sessions/{session_id}/candidates/{c['candidate_id']}/review",
            json={"decision": "EXCLUDE"},
        )

    preview2 = client.get(f"/api/sessions/{session_id}/preview").json()["candidates"]
    keep = next(c for c in preview2 if c["candidate_id"] == keep["candidate_id"])
    drop = next(c for c in preview2 if c["candidate_id"] == drop["candidate_id"])
    assert keep["exportable"] is True
    assert drop["exportable"] is True
    return session_id, keep, drop


def _sale_price_at(path: Path, row_number: int) -> str:
    wb = load_workbook(path, read_only=True, data_only=True)
    ws = wb.active
    headers = [c.value for c in next(ws.iter_rows(min_row=1, max_row=1))]
    sale_idx = headers.index("نرخ فروش اصلی")
    vals = [
        c.value
        for c in next(ws.iter_rows(min_row=row_number, max_row=row_number))
    ]
    wb.close()
    return str(vals[sale_idx]).replace(",", "")


def test_order_exclude_then_export_omits_excluded_row(
    client, pioneers_azin_excel: Path, azin_pdf: Path, tmp_path: Path
) -> None:
    """Intended order: exclusion completes before export snapshots."""
    session_id, keep, drop = _prepare_two_exportable(
        client, pioneers_azin_excel, azin_pdf
    )

    exclude = client.post(
        f"/api/sessions/{session_id}/candidates/{drop['candidate_id']}/review",
        json={"decision": "EXCLUDE"},
    )
    assert exclude.status_code == 200
    assert exclude.json()["exportable"] is False

    export = client.post(f"/api/sessions/{session_id}/export")
    assert export.status_code == 200
    assert export.json()["updated_count"] == 1

    download = client.get(f"/api/sessions/{session_id}/download")
    assert download.status_code == 200
    out = tmp_path / "exclude_then_export.xlsx"
    out.write_bytes(download.content)

    assert _sale_price_at(out, keep["row_number"]) == str(keep["new_price"]).replace(
        ",", ""
    )
    assert _sale_price_at(out, drop["row_number"]) == str(drop["old_price"]).replace(
        ",", ""
    )


def test_order_export_then_exclude_invalidates_stale_download(
    client, pioneers_azin_excel: Path, azin_pdf: Path, tmp_path: Path
) -> None:
    """Opposite order: export first, then exclude must invalidate that export."""
    session_id, keep, drop = _prepare_two_exportable(
        client, pioneers_azin_excel, azin_pdf
    )

    export = client.post(f"/api/sessions/{session_id}/export")
    assert export.status_code == 200
    assert export.json()["updated_count"] == 2

    download = client.get(f"/api/sessions/{session_id}/download")
    assert download.status_code == 200
    first = tmp_path / "export_first.xlsx"
    first.write_bytes(download.content)
    # Both rows were exportable at snapshot time.
    assert _sale_price_at(first, drop["row_number"]) == str(drop["new_price"]).replace(
        ",", ""
    )

    exclude = client.post(
        f"/api/sessions/{session_id}/candidates/{drop['candidate_id']}/review",
        json={"decision": "EXCLUDE"},
    )
    assert exclude.status_code == 200
    # Exclusion invalidates prior export artifact.
    stale = client.get(f"/api/sessions/{session_id}/download")
    assert stale.status_code == 404

    re_export = client.post(f"/api/sessions/{session_id}/export")
    assert re_export.status_code == 200
    assert re_export.json()["updated_count"] == 1

    download2 = client.get(f"/api/sessions/{session_id}/download")
    assert download2.status_code == 200
    second = tmp_path / "export_after_exclude.xlsx"
    second.write_bytes(download2.content)
    assert _sale_price_at(second, keep["row_number"]) == str(keep["new_price"]).replace(
        ",", ""
    )
    assert _sale_price_at(second, drop["row_number"]) == str(drop["old_price"]).replace(
        ",", ""
    )
