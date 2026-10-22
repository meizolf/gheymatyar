"""Image-only and undecodable price lists stay unsupported.

Pars Plast and Kaveh Gostar are scanned pages with no text layer.
PG 234 embeds Identity-H fonts whose Unicode map does not contain the
printed prices. Offline Tesseract (engine plus Persian language data) is
not bundled, and this machine cannot verify a Windows onedir OCR package,
so these suppliers are not registered.
"""

from __future__ import annotations

from pathlib import Path

import pymupdf

from gheymatyar.suppliers.registry import get_default_registry


def _text_length(path: Path) -> int:
    doc = pymupdf.open(path)
    try:
        return sum(len((page.get_text("text") or "").strip()) for page in doc)
    finally:
        doc.close()


def test_pars_plast_has_no_text_layer(pars_plast_pdf: Path) -> None:
    assert _text_length(pars_plast_pdf) == 0
    assert "pars_plast" not in get_default_registry().keys()


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
