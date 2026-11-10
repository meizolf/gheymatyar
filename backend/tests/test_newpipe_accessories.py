"""NewPipe accessories list (two pages, two tables per page) on the NewPipe processor.

Expected prices were read off the rendered pages. The older NewPipe pipe
list stays covered by test_additional_supplier_pdfs.py.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from gheymatyar.domain.enums import MatchStatus
from gheymatyar.domain.product import PioneersProduct
from gheymatyar.services.matching import SavedNameMapping, match_supplier_items
from gheymatyar.services.product_identity import supplier_product_identity
from gheymatyar.suppliers.detection import Confidence, SupplierDetector, matching_strong_markers
from gheymatyar.suppliers.errors import SupplierPdfError
from gheymatyar.suppliers.newpipe import NewPipeProcessor
from gheymatyar.suppliers.registry import get_default_registry

from .conftest import NEWPIPE_ACCESSORIES_PDF, _require_pdf

NP = "نیوپایپ "


@pytest.fixture(scope="module")
def result():
    return NewPipeProcessor().parse_pdf(_require_pdf(NEWPIPE_ACCESSORIES_PDF))


def _item(result, code: str):
    return next(item for item in result.items if item.supplier_code == code)


@pytest.mark.parametrize(
    ("code", "rial", "name", "column"),
    [
        ("807221010", 12_276_660, "پروفیل های فلزی پروفیل C شکل 49x27x1.5mm 2 متری", "right"),
        ("807323035", 31_805_070, "جعبه کلکتور همراه با پایه و بست 35*45", "left"),
        ("861662009", 46_000_000, "ترموستات اتاقی لمسی تک فصل دیجیتالی SGP سفید", "left"),
        # Same row, other table; mixed inch fraction; heading split over two spans.
        ("807221015", 10_230_550, "پروفیل های فلزی پروفیل C شکل 35x25x1.5mm 2 متری", "right"),
        ("807241504", 247_390, "بست کلکتور 1 1/4", "left"),
        ("891771277", 5_729_130, "چسب فشار قوی PVC 250 گرمی", "left"),
        ("807261301", 152_240, "درپوش پایه بلند پلاستیکی طرح جدید 1/2 آبی", "right"),
        ("807261401", 233_640, "درپوش پایه بلند پلاستیکی 1/2 آبی", "right"),
    ],
)
def test_accessories_prices_and_names(result, code, rial, name, column) -> None:
    item = _item(result, code)
    assert item.price == Decimal(rial)  # printed Rial incl. VAT, never × box/carton
    assert item.supplier_name == NP + name
    assert item.raw_values["column"] == column


def test_accessories_list_is_complete_and_vat_inclusive(result) -> None:
    assert result.supplier_key == "newpipe"
    assert len(result.items) == 92 and not result.warnings
    assert len({item.supplier_name for item in result.items}) == 92
    assert result.source_metadata["pricing_rule"] == "direct_replacement_vat_inclusive"
    processor = NewPipeProcessor()
    assert all(processor.calculate_final_sale_price(i) == i.price for i in result.items)


def test_accessories_identify_as_newpipe_only_with_title_and_newbox() -> None:
    pdf = _require_pdf(NEWPIPE_ACCESSORIES_PDF)
    registry = get_default_registry()
    detected = SupplierDetector(registry).detect(pdf)
    assert (detected.detected_supplier_id, detected.confidence) == ("newpipe", Confidence.HIGH)
    assert detected.requires_confirmation
    registry.validate_pdf_for_supplier(pdf, "newpipe")
    with pytest.raises(SupplierPdfError):
        registry.validate_pdf_for_supplier(pdf, "dina_polymer")
    # Gitikala/SGP branding or the title alone is not NewPipe.
    rules = NewPipeProcessor().detection_rules()
    generic = "Gitikala SGP گیتی کالا لیست قیمت ملزومات سیستم لوله کشی تاسیسات پلیمری"
    assert matching_strong_markers(generic, rules) == []


def test_accessories_reuse_saved_newpipe_mappings(result) -> None:
    processor = get_default_registry().get("newpipe")
    item = _item(result, "807221010")
    normalized = processor.normalize_supplier_name(item.supplier_name)
    saved = SavedNameMapping(
        supplier_name_normalized=normalized,
        pioneers_name_raw="پروفیل C شکل 49x27",
        pioneers_name_normalized="پروفیل c شکل 49x27",
        pioneers_code="9001",
        identity_key=supplier_product_identity(normalized_name=normalized, supplier_code="807221010"),
        supplier_code="807221010",
    )
    products = [PioneersProduct(row_number=2, code="9001", name="پروفیل C شکل 49x27",
                                sale_price=Decimal("1000"))]
    matched = match_supplier_items([item], products, processor=processor, saved_mappings=[saved])
    assert [(c.status, c.pioneers_code) for c in matched.candidates] == [(MatchStatus.MATCHED, "9001")]
