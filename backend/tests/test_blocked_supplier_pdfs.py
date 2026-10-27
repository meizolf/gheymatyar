"""Image-only and undecodable price lists stay unsupported.

Pars Plast and Kaveh Gostar are scanned pages with no text layer.
PG 234 embeds Identity-H fonts whose Unicode map does not contain the
printed prices. Offline Tesseract (engine plus Persian language data) is
not bundled, and this machine cannot verify a Windows onedir OCR package,
so these suppliers are not registered as PDF suppliers. Pars Plast prices
are read from its website instead (see ``suppliers/pars_plast.py``).
"""

from __future__ import annotations

from pathlib import Path

import pymupdf
import pytest

from gheymatyar.suppliers.errors import SupplierPdfError
from gheymatyar.suppliers.registry import get_default_registry


def _text_length(path: Path) -> int:
    doc = pymupdf.open(path)
    try:
        return sum(len((page.get_text("text") or "").strip()) for page in doc)
    finally:
        doc.close()


def test_pars_plast_has_no_text_layer(pars_plast_pdf: Path) -> None:
    """Its prices come from the website; the scanned PDF is still refused."""
    assert _text_length(pars_plast_pdf) == 0
    registry = get_default_registry()
    assert "pars_plast" not in {info.key for info in registry.pdf_suppliers()}
    with pytest.raises(SupplierPdfError, match="come from its website"):
        registry.validate_pdf_for_supplier(pars_plast_pdf, "pars_plast")
    assert registry.detect(pars_plast_pdf).detected_supplier_id is None


def test_pars_plast_pdf_upload_is_refused(client, pars_plast_pdf: Path) -> None:
    session_id = client.post("/api/sessions").json()["session_id"]
    with pars_plast_pdf.open("rb") as handle:
        response = client.post(
            f"/api/sessions/{session_id}/supplier-pdf",
            data={"supplier_key": "pars_plast"},
            files={"file": ("pars.pdf", handle, "application/pdf")},
        )
    assert response.status_code == 400
    assert "website" in response.json()["detail"]


def test_kaveh_gostar_has_no_text_layer(kaveh_pdf: Path) -> None:
    assert _text_length(kaveh_pdf) == 0
    assert "kaveh_gostar" not in get_default_registry().keys()


def test_pg234_text_layer_does_not_contain_printed_prices(pg234_pdf: Path) -> None:
    """Codes such as ``PG 0022 P`` can appear, but the Rial amounts do not.

    The visual table on physical page 2 prints 6,260,000 Rial per branch for
    that code. The extracted text never contains that amount, so the row
    cannot be priced safely.
    """
    doc = pymupdf.open(pg234_pdf)
    try:
        text = "\n".join((page.get_text("text") or "") for page in doc)
    finally:
        doc.close()
    assert "PG 0022" in text
    assert "6,260,000" not in text
    assert "6260000" not in text
    assert "6,226,000" not in text
    assert "polymer_golpayegan" not in get_default_registry().keys()
