"""Mapping confirmation must not clear genuine supplier price restrictions."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from tests.confirmed_metre import prepare_two_exportable_metre_rows


def _upload_and_match(
    client: TestClient,
    excel: Path,
    pdf: Path,
    supplier_key: str,
) -> str:
    session_id = client.post("/api/sessions").json()["session_id"]
    with excel.open("rb") as handle:
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
    with pdf.open("rb") as handle:
        pdf_resp = client.post(
            f"/api/sessions/{session_id}/supplier-pdf",
            data={"supplier_key": supplier_key},
            files={"file": ("list.pdf", handle, "application/pdf")},
        )
    assert pdf_resp.status_code == 200, pdf_resp.text
    match_resp = client.post(f"/api/sessions/{session_id}/match", json={})
    assert match_resp.status_code == 200, match_resp.text
    return session_id


def _first_product_row(client: TestClient, session_id: str) -> int:
    search = client.get(
        f"/api/sessions/{session_id}/pioneers-products/search",
        params={"q": "لوله"},
    )
    assert search.status_code == 200, search.text
    results = search.json()["results"]
    assert results
    return int(results[0]["row_number"])


def _candidate(client: TestClient, session_id: str, **needle: str) -> dict:
    listed = client.get(f"/api/sessions/{session_id}/candidates")
    assert listed.status_code == 200, listed.text
    for candidate in listed.json()["candidates"]:
        if all(str(candidate.get(key)) == value for key, value in needle.items()):
            return candidate
    raise AssertionError(f"candidate not found: {needle}")


def _confirm_still_blocked(
    client: TestClient,
    *,
    excel: Path,
    pdf: Path,
    supplier_key: str,
    needle: dict[str, str],
    warning_fragment: str,
) -> None:
    session_id = _upload_and_match(client, excel, pdf, supplier_key)
    row_number = _first_product_row(client, session_id)
    original = _candidate(client, session_id, **needle)
    assert original["exportable"] is False
    assert any(warning_fragment in warning for warning in original["pricing_blockers"])

    confirmed = client.post(
        f"/api/sessions/{session_id}/candidates/{original['candidate_id']}/confirm-mapping",
        json={"pioneers_row_number": row_number, "save": True},
    )
    assert confirmed.status_code == 200, confirmed.text
    body = confirmed.json()
    assert body["status"] == "MATCHED"
    assert body["exportable"] is False
    assert any(warning_fragment in warning for warning in body["pricing_blockers"])
    assert any(warning_fragment in warning for warning in body["warnings"])
    assert body["source_currency"]
    assert body["price_basis"]

    approved = client.post(
        f"/api/sessions/{session_id}/candidates/{original['candidate_id']}/review",
        json={"decision": "APPROVE"},
    )
    assert approved.status_code == 400
    assert "unresolved" in approved.json()["detail"]

    listed = client.get(f"/api/sessions/{session_id}/candidates")
    for candidate in listed.json()["candidates"]:
        if candidate["candidate_id"] == original["candidate_id"] or not candidate["exportable"]:
            continue
        excluded = client.post(
            f"/api/sessions/{session_id}/candidates/{candidate['candidate_id']}/review",
            json={"decision": "EXCLUDE"},
        )
        assert excluded.status_code == 200, excluded.text

    exported = client.post(f"/api/sessions/{session_id}/export")
    assert exported.status_code == 400

    reused_id = _upload_and_match(client, excel, pdf, supplier_key)
    reused = _candidate(client, reused_id, **needle)
    assert reused["match_type"] == "SAVED_MAPPING"
    assert reused["status"] == "MATCHED"
    assert reused["exportable"] is False
    assert any(warning_fragment in warning for warning in reused["pricing_blockers"])


def test_confirm_mapping_keeps_dina_drip_name_collision_block(
    client: TestClient, pioneers_azin_excel: Path, dina_pdf: Path
) -> None:
    """Duplicate drip descriptors with distinct codes stay blocked after mapping."""
    _confirm_still_blocked(
        client,
        excel=pioneers_azin_excel,
        pdf=dina_pdf,
        supplier_key="dina_polymer",
        needle={"supplier_code": "825952020", "new_price": "198440"},
        warning_fragment="shared by products",
    )


def _revoke_sale_policy(client: TestClient) -> None:
    cleared = client.put(
        "/api/settings",
        json={
            "settings": {
                "pioneers_sale_currency": "",
                "pioneers_sale_basis": "piece",
            }
        },
    )
    assert cleared.status_code == 200, cleared.text


def test_clearing_sale_policy_blocks_first_export(
    client: TestClient,
    pioneers_azin_excel: Path,
    dina_pdf: Path,
    tmp_path: Path,
) -> None:
    session_id, keep, drop = prepare_two_exportable_metre_rows(
        client, pioneers_azin_excel, dina_pdf, tmp_path
    )
    assert client.get(f"/api/sessions/{session_id}/download").status_code == 404

    _revoke_sale_policy(client)
    preview = client.get(f"/api/sessions/{session_id}/preview").json()["candidates"]
    for code in (keep["supplier_code"], drop["supplier_code"]):
        row = next(item for item in preview if item["supplier_code"] == code)
        assert row["exportable"] is False
        assert row["new_price"] == (
            keep["new_price"] if code == keep["supplier_code"] else drop["new_price"]
        )
        assert row["pricing_blockers"]
        approved = client.post(
            f"/api/sessions/{session_id}/candidates/{row['candidate_id']}/review",
            json={"decision": "APPROVE"},
        )
        assert approved.status_code == 400

    exported = client.post(f"/api/sessions/{session_id}/export")
    assert exported.status_code == 400
    assert client.get(f"/api/sessions/{session_id}/download").status_code == 404


def test_revoking_sale_policy_drops_existing_workbook(
    client: TestClient,
    pioneers_azin_excel: Path,
    dina_pdf: Path,
    tmp_path: Path,
) -> None:
    session_id, keep, _drop = prepare_two_exportable_metre_rows(
        client, pioneers_azin_excel, dina_pdf, tmp_path
    )
    exported = client.post(f"/api/sessions/{session_id}/export")
    assert exported.status_code == 200, exported.text
    first = client.get(f"/api/sessions/{session_id}/download")
    assert first.status_code == 200
    assert len(first.content) > 1000

    _revoke_sale_policy(client)
    assert client.get(f"/api/sessions/{session_id}/download").status_code == 404
    again = client.post(f"/api/sessions/{session_id}/export")
    assert again.status_code == 400
    assert client.get(f"/api/sessions/{session_id}/download").status_code == 404
    preview = client.get(f"/api/sessions/{session_id}/preview").json()["candidates"]
    row = next(item for item in preview if item["supplier_code"] == keep["supplier_code"])
    assert row["exportable"] is False
    assert row["new_price"] == keep["new_price"]


def test_default_settings_confirm_pioneers_sale_currency_is_rial(client: TestClient) -> None:
    body = client.get("/api/settings").json()["settings"]
    assert body["pioneers_sale_currency"] == "rial"
