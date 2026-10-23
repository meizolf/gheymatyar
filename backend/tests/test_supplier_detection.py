"""SupplierDetector: content-based identification and confirmation safety."""

from __future__ import annotations

from pathlib import Path

import pytest

from gheymatyar.suppliers.detection import (
    Confidence,
    SupplierDetector,
    extract_pdf_text_for_detection,
    try_offline_ocr,
)
from gheymatyar.suppliers.errors import SupplierPdfError
from gheymatyar.suppliers.registry import get_default_registry


@pytest.fixture(scope="module")
def detector() -> SupplierDetector:
    return SupplierDetector(get_default_registry())


@pytest.mark.parametrize(
    ("pdf_fixture", "expected_key", "min_confidence"),
    [
        ("azin_pdf", "azin_pipe", Confidence.HIGH),
        ("top_pdf", "top_industrial", Confidence.HIGH),
        ("dina_pdf", "dina_polymer", Confidence.HIGH),
        ("newpipe_pdf", "newpipe", Confidence.HIGH),
        ("abrahan_pdf", "abrahan_pipe", Confidence.HIGH),
    ],
)
def test_detects_each_registered_supplier(
    detector: SupplierDetector,
    pdf_fixture: str,
    expected_key: str,
    min_confidence: Confidence,
    request: pytest.FixtureRequest,
) -> None:
    path: Path = request.getfixturevalue(pdf_fixture)
    result = detector.detect(path)
    assert result.detected_supplier_id == expected_key
    assert result.requires_confirmation is True
    assert result.confidence is min_confidence
    assert result.evidence
    assert result.text_extracted is True


def test_detection_ignores_misleading_filename(
    detector: SupplierDetector, azin_pdf: Path, tmp_path: Path
) -> None:
    renamed = tmp_path / "newpipe_fake_name.pdf"
    renamed.write_bytes(azin_pdf.read_bytes())
    result = detector.detect(renamed)
    assert result.detected_supplier_id == "azin_pipe"
    assert result.confidence is Confidence.HIGH


def test_unknown_supplier_pg234(detector: SupplierDetector, pg234_pdf: Path) -> None:
    result = detector.detect(pg234_pdf)
    assert result.detected_supplier_id is None
    assert result.confidence is Confidence.UNKNOWN
    assert result.requires_confirmation is True


def test_scanned_pdf_without_ocr_is_unknown(
    detector: SupplierDetector, pars_plast_pdf: Path
) -> None:
    text, has_text = extract_pdf_text_for_detection(pars_plast_pdf)
    assert has_text is False
    assert text.strip() == ""
    # OCR is optional and not bundled; empty OCR → UNKNOWN.
    ocr = try_offline_ocr(pars_plast_pdf)
    result = detector.detect(pars_plast_pdf)
    assert result.detected_supplier_id is None
    assert result.confidence is Confidence.UNKNOWN
    assert "no_text_layer" in result.evidence
    if not ocr.strip():
        assert result.ocr_used is False


def test_kaveh_scanned_is_unknown(detector: SupplierDetector, kaveh_pdf: Path) -> None:
    result = detector.detect(kaveh_pdf)
    assert result.confidence is Confidence.UNKNOWN
    assert result.detected_supplier_id is None


def test_conflicting_brands_are_not_high_confidence(
    detector: SupplierDetector, tmp_path: Path
) -> None:
    from gheymatyar.suppliers import detection as detection_mod

    original = detection_mod.extract_pdf_text_for_detection

    def fake_extract(_path, *, max_pages: int | None = 3):  # noqa: ARG001
        return "آذین لوله و نیوپایپ", True

    detection_mod.extract_pdf_text_for_detection = fake_extract  # type: ignore[assignment]
    try:
        dummy = tmp_path / "multi.pdf"
        dummy.write_bytes(b"%PDF-1.4\n")
        result = detector.detect(dummy)
        assert result.confidence is not Confidence.HIGH
        assert result.confidence in {Confidence.LOW, Confidence.UNKNOWN}
        # Tied strong brands → no confident assignment.
        if result.scores.get("azin_pipe") == result.scores.get("newpipe"):
            assert result.detected_supplier_id is None
            assert result.confidence is Confidence.UNKNOWN
    finally:
        detection_mod.extract_pdf_text_for_detection = original  # type: ignore[assignment]


def test_overlapping_aliases_do_not_double_count(
    detector: SupplierDetector, tmp_path: Path
) -> None:
    from gheymatyar.suppliers import detection as detection_mod

    original = detection_mod.extract_pdf_text_for_detection

    def fake_extract(_path, *, max_pages: int | None = 3):  # noqa: ARG001
        return "لیست قیمت لوله و اتصالات پلی پروپیلن آذین لوله", True

    detection_mod.extract_pdf_text_for_detection = fake_extract  # type: ignore[assignment]
    try:
        dummy = tmp_path / "azin_alias.pdf"
        dummy.write_bytes(b"%PDF-1.4\n")
        result = detector.detect(dummy)
        assert result.detected_supplier_id == "azin_pipe"
        # One identity credit (+10) even though آذین لوله and آذین both match.
        assert result.scores["azin_pipe"] < 20
        assert "آذین لوله" in result.evidence
    finally:
        detection_mod.extract_pdf_text_for_detection = original  # type: ignore[assignment]


def test_generic_terms_alone_are_unknown(
    detector: SupplierDetector, tmp_path: Path
) -> None:
    from gheymatyar.suppliers import detection as detection_mod

    original = detection_mod.extract_pdf_text_for_detection

    def fake_extract(_path, *, max_pages: int | None = 3):  # noqa: ARG001
        return "قیمت هر متر — واحد تومان", True

    detection_mod.extract_pdf_text_for_detection = fake_extract  # type: ignore[assignment]
    try:
        dummy = tmp_path / "generic.pdf"
        dummy.write_bytes(b"%PDF-1.4\n")
        result = detector.detect(dummy)
        assert result.detected_supplier_id is None
        assert result.confidence is Confidence.UNKNOWN
        assert result.scores["top_industrial"] == 0
        assert result.scores["dina_polymer"] == 0
    finally:
        detection_mod.extract_pdf_text_for_detection = original  # type: ignore[assignment]


def test_registry_detect_delegates(azin_pdf: Path) -> None:
    result = get_default_registry().detect(azin_pdf)
    assert result.detected_supplier_id == "azin_pipe"


def test_detect_api_does_not_parse_prices(
    client, azin_pdf: Path, pioneers_azin_excel: Path
) -> None:
    session_id = client.post("/api/sessions").json()["session_id"]
    with pioneers_azin_excel.open("rb") as handle:
        excel = client.post(
            f"/api/sessions/{session_id}/pioneers-excel",
            files={
                "file": (
                    "pioneers.xlsx",
                    handle,
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
            },
        )
    assert excel.status_code == 200, excel.text

    with azin_pdf.open("rb") as handle:
        response = client.post(
            f"/api/sessions/{session_id}/supplier-pdf/detect",
            files={"file": ("azin.pdf", handle, "application/pdf")},
        )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["supplier_confirmed"] is False
    assert body["detection"]["detected_supplier_id"] == "azin_pipe"
    assert body["detection"]["confidence"] == "HIGH"
    assert body["detection"]["requires_confirmation"] is True
    assert body["summary"]["supplier_item_count"] == 0
    assert body["summary"]["supplier_confirmed"] is False

    # Matching must refuse before confirmation.
    match = client.post(f"/api/sessions/{session_id}/match", json={})
    assert match.status_code == 400
    assert "confirm" in match.json()["detail"].lower()


def test_confirm_api_parses_prices(client, azin_pdf: Path) -> None:
    session_id = client.post("/api/sessions").json()["session_id"]
    with azin_pdf.open("rb") as handle:
        detect = client.post(
            f"/api/sessions/{session_id}/supplier-pdf/detect",
            files={"file": ("wrong_name_newpipe.pdf", handle, "application/pdf")},
        )
    assert detect.status_code == 200
    assert detect.json()["detection"]["detected_supplier_id"] == "azin_pipe"

    confirm = client.post(
        f"/api/sessions/{session_id}/supplier-pdf/confirm",
        json={"supplier_key": "azin_pipe"},
    )
    assert confirm.status_code == 200, confirm.text
    body = confirm.json()
    assert body["supplier_confirmed"] is True
    assert body["supplier_key"] == "azin_pipe"
    assert body["supplier_item_count"] >= 200


def test_manual_override_on_confirm(client, azin_pdf: Path) -> None:
    """User may override the suggestion; wrong processor must fail clearly."""
    session_id = client.post("/api/sessions").json()["session_id"]
    with azin_pdf.open("rb") as handle:
        client.post(
            f"/api/sessions/{session_id}/supplier-pdf/detect",
            files={"file": ("azin.pdf", handle, "application/pdf")},
        )
    # Confirming as TOP against an Azin PDF should not silently succeed.
    bad = client.post(
        f"/api/sessions/{session_id}/supplier-pdf/confirm",
        json={"supplier_key": "top_industrial"},
    )
    assert bad.status_code == 400
    # PDF remains for a corrected confirmation.
    good = client.post(
        f"/api/sessions/{session_id}/supplier-pdf/confirm",
        json={"supplier_key": "azin_pipe"},
    )
    assert good.status_code == 200
    assert good.json()["supplier_item_count"] >= 200


def test_pdf_replacement_resets_confirmation(client, azin_pdf: Path, newpipe_pdf: Path) -> None:
    session_id = client.post("/api/sessions").json()["session_id"]
    with azin_pdf.open("rb") as handle:
        client.post(
            f"/api/sessions/{session_id}/supplier-pdf/detect",
            files={"file": ("azin.pdf", handle, "application/pdf")},
        )
    confirm = client.post(
        f"/api/sessions/{session_id}/supplier-pdf/confirm",
        json={"supplier_key": "azin_pipe"},
    )
    assert confirm.json()["supplier_confirmed"] is True
    assert confirm.json()["supplier_item_count"] > 0

    with newpipe_pdf.open("rb") as handle:
        again = client.post(
            f"/api/sessions/{session_id}/supplier-pdf/detect",
            files={"file": ("newpipe.pdf", handle, "application/pdf")},
        )
    body = again.json()
    assert body["supplier_confirmed"] is False
    assert body["summary"]["supplier_item_count"] == 0
    assert body["detection"]["detected_supplier_id"] == "newpipe"


def test_legacy_upload_still_confirms(client, azin_pdf: Path) -> None:
    session_id = client.post("/api/sessions").json()["session_id"]
    with azin_pdf.open("rb") as handle:
        response = client.post(
            f"/api/sessions/{session_id}/supplier-pdf",
            data={"supplier_key": "azin_pipe"},
            files={"file": ("azin.pdf", handle, "application/pdf")},
        )
    assert response.status_code == 200
    assert response.json()["supplier_confirmed"] is True
    assert response.json()["supplier_item_count"] >= 200


def test_confirm_without_pdf_errors(client) -> None:
    session_id = client.post("/api/sessions").json()["session_id"]
    response = client.post(
        f"/api/sessions/{session_id}/supplier-pdf/confirm",
        json={"supplier_key": "azin_pipe"},
    )
    assert response.status_code == 400


def test_incompatible_confirm_raises_supplier_pdf_error(
    client, top_pdf: Path
) -> None:
    session_id = client.post("/api/sessions").json()["session_id"]
    with top_pdf.open("rb") as handle:
        client.post(
            f"/api/sessions/{session_id}/supplier-pdf/detect",
            files={"file": ("top.pdf", handle, "application/pdf")},
        )
    response = client.post(
        f"/api/sessions/{session_id}/supplier-pdf/confirm",
        json={"supplier_key": "azin_pipe"},
    )
    assert response.status_code == 400
    assert "does not identify" in response.json()["detail"].lower()
    with pytest.raises(SupplierPdfError):
        get_default_registry().get("azin_pipe").validate_pdf_identity(top_pdf)


@pytest.mark.parametrize(
    ("pdf_fixture", "wrong_key"),
    [
        ("azin_pdf", "dina_polymer"),
        ("dina_pdf", "azin_pipe"),
        ("dina_pdf", "abrahan_pipe"),
        ("newpipe_pdf", "dina_polymer"),
    ],
)
def test_wrong_manual_selection_is_rejected(
    client,
    pdf_fixture: str,
    wrong_key: str,
    request: pytest.FixtureRequest,
) -> None:
    path: Path = request.getfixturevalue(pdf_fixture)
    session_id = client.post("/api/sessions").json()["session_id"]
    with path.open("rb") as handle:
        detect = client.post(
            f"/api/sessions/{session_id}/supplier-pdf/detect",
            files={"file": ("list.pdf", handle, "application/pdf")},
        )
    assert detect.status_code == 200
    bad = client.post(
        f"/api/sessions/{session_id}/supplier-pdf/confirm",
        json={"supplier_key": wrong_key},
    )
    assert bad.status_code == 400
    assert "does not identify" in bad.json()["detail"].lower()
    summary = client.get(f"/api/sessions/{session_id}").json()
    assert summary["supplier_confirmed"] is False
    assert summary["supplier_item_count"] == 0


def test_failed_reconfirm_clears_downstream_and_blocks_export(
    client, azin_pdf: Path, pioneers_azin_excel: Path
) -> None:
    session_id = client.post("/api/sessions").json()["session_id"]
    with pioneers_azin_excel.open("rb") as handle:
        assert (
            client.post(
                f"/api/sessions/{session_id}/pioneers-excel",
                files={
                    "file": (
                        "pioneers.xlsx",
                        handle,
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    )
                },
            ).status_code
            == 200
        )
    with azin_pdf.open("rb") as handle:
        client.post(
            f"/api/sessions/{session_id}/supplier-pdf/detect",
            files={"file": ("azin.pdf", handle, "application/pdf")},
        )
    confirm = client.post(
        f"/api/sessions/{session_id}/supplier-pdf/confirm",
        json={"supplier_key": "azin_pipe"},
    )
    assert confirm.status_code == 200
    match = client.post(f"/api/sessions/{session_id}/match", json={})
    assert match.status_code == 200
    assert match.json()["candidates"]

    # Wrong supplier on the same uploaded PDF must revoke confirmation/results.
    bad = client.post(
        f"/api/sessions/{session_id}/supplier-pdf/confirm",
        json={"supplier_key": "dina_polymer"},
    )
    assert bad.status_code == 400
    assert "does not identify" in bad.json()["detail"].lower()
    summary = client.get(f"/api/sessions/{session_id}").json()
    assert summary["supplier_confirmed"] is False
    assert summary["supplier_item_count"] == 0
    assert summary["matched_count"] == 0
    assert summary["export_available"] is False
    # Upload is preserved for a corrected confirmation.
    assert summary["pdf_filename"] == "azin.pdf"

    export = client.post(f"/api/sessions/{session_id}/export")
    assert export.status_code == 400
    assert "confirm" in export.json()["detail"].lower()
    download = client.get(f"/api/sessions/{session_id}/download")
    assert download.status_code == 400
    assert "confirm" in download.json()["detail"].lower()


def test_mixed_supplier_pdf_rejects_confirmation(
    client, dina_pdf: Path, newpipe_pdf: Path, tmp_path: Path
) -> None:
    """A document with multiple brand sections must not parse as either one."""
    import pymupdf

    mixed = tmp_path / "dina_plus_newpipe.pdf"
    dina_doc = pymupdf.open(dina_pdf)
    newpipe_doc = pymupdf.open(newpipe_pdf)
    out = pymupdf.open()
    try:
        out.insert_pdf(dina_doc, from_page=0, to_page=0)
        out.insert_pdf(newpipe_doc, from_page=0, to_page=0)
        out.save(mixed)
    finally:
        dina_doc.close()
        newpipe_doc.close()
        out.close()

    detection = get_default_registry().detect(mixed)
    assert detection.confidence is Confidence.UNKNOWN
    assert detection.detected_supplier_id is None

    session_id = client.post("/api/sessions").json()["session_id"]
    with mixed.open("rb") as handle:
        detect = client.post(
            f"/api/sessions/{session_id}/supplier-pdf/detect",
            files={"file": ("mixed.pdf", handle, "application/pdf")},
        )
    assert detect.status_code == 200
    assert detect.json()["detection"]["confidence"] == "UNKNOWN"

    for wrong_key in ("dina_polymer", "newpipe"):
        bad = client.post(
            f"/api/sessions/{session_id}/supplier-pdf/confirm",
            json={"supplier_key": wrong_key},
        )
        assert bad.status_code == 400, wrong_key
        detail = bad.json()["detail"].lower()
        assert "mixed" in detail or "also identifies" in detail
        summary = client.get(f"/api/sessions/{session_id}").json()
        assert summary["supplier_confirmed"] is False
        assert summary["supplier_item_count"] == 0


def test_detection_error_keeps_pdf_for_manual_confirm(
    client, azin_pdf: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from gheymatyar.suppliers.registry import SupplierProcessorRegistry

    def boom(self, path):  # noqa: ANN001, ARG001
        raise RuntimeError("simulated detector crash")

    monkeypatch.setattr(SupplierProcessorRegistry, "detect", boom)
    session_id = client.post("/api/sessions").json()["session_id"]
    with azin_pdf.open("rb") as handle:
        response = client.post(
            f"/api/sessions/{session_id}/supplier-pdf/detect",
            files={"file": ("azin.pdf", handle, "application/pdf")},
        )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["pdf_filename"] == "azin.pdf"
    assert body["detection"]["confidence"] == "UNKNOWN"
    assert "detection_error" in body["detection"]["evidence"]
    assert body["summary"]["pdf_filename"] == "azin.pdf"

    # Manual confirmation still works against the preserved upload.
    confirm = client.post(
        f"/api/sessions/{session_id}/supplier-pdf/confirm",
        json={"supplier_key": "azin_pipe"},
    )
    assert confirm.status_code == 200, confirm.text
    assert confirm.json()["supplier_confirmed"] is True
    assert confirm.json()["supplier_item_count"] >= 200
