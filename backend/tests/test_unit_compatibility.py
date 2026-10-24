"""Per-metre prices must not replace a branch sale price, and a blank workbook unit stays unresolved."""

from __future__ import annotations

from decimal import Decimal

from gheymatyar.domain.enums import ReviewDecision
from gheymatyar.domain.product import PioneersProduct
from gheymatyar.parsers.pioneers_excel_parser import PioneersExcelParser
from gheymatyar.services.matching import match_supplier_items
from gheymatyar.services.price_validation import apply_price_warnings, is_exportable
from gheymatyar.suppliers.dina_polymer import DinaPolymerProcessor


def _pipe(dina_pdf):
    parsed = DinaPolymerProcessor().parse_pdf(dina_pdf)
    return next(item for item in parsed.items if item.supplier_code == "825331050")


def test_metre_price_is_not_exportable_for_a_branch_unit(dina_pdf) -> None:
    item = _pipe(dina_pdf)
    assert item.unit == "متر"
    assert item.raw_values["price_basis"] == "meter"
    assert item.price == Decimal("909370")
    product = PioneersProduct(
        row_number=2,
        name=item.supplier_name,
        code="D-METRE",
        unit="شاخه 6 متری",
        sale_price=item.price + 1,
    )
    matched = match_supplier_items(
        [item], [product], processor=DinaPolymerProcessor()
    )
    enriched = apply_price_warnings(matched.candidates)
    candidate = enriched[0]
    assert candidate.status == "MATCHED"
    assert candidate.new_price == Decimal("909370")
    assert candidate.new_price != item.price * 6
    assert candidate.price_basis == "meter"
    assert candidate.source_unit == "متر"
    assert any("per metre" in blocker for blocker in candidate.pricing_blockers)
    assert any("شاخه 6 متری" in blocker for blocker in candidate.pricing_blockers)
    assert any("no conversion" in blocker for blocker in candidate.pricing_blockers)
    assert is_exportable(candidate) is False
    approved = candidate.model_copy(update={"review_decision": ReviewDecision.APPROVE})
    assert is_exportable(approved) is False


def test_real_workbook_without_a_unit_column_uses_the_printed_rial_amount(
    dina_pdf, pioneers_azin_excel
) -> None:
    parsed = PioneersExcelParser().parse(pioneers_azin_excel)
    assert parsed.products
    assert all(product.unit is None for product in parsed.products)
    item = _pipe(dina_pdf)
    target = parsed.products[0].model_copy(update={"name": item.supplier_name})
    matched = match_supplier_items(
        [item],
        [target],
        processor=DinaPolymerProcessor(),
    )
    enriched = apply_price_warnings(matched.candidates)
    candidate = enriched[0]
    assert candidate.new_price == item.price
    assert candidate.new_price != item.price * 6
    assert candidate.pricing_blockers == []


def test_matching_metre_units_do_not_multiply_the_price(dina_pdf) -> None:
    item = _pipe(dina_pdf)
    product = PioneersProduct(
        row_number=2,
        name=item.supplier_name,
        code="D-M",
        unit="متر",
        sale_price=item.price,
    )
    matched = match_supplier_items(
        [item],
        [product],
        processor=DinaPolymerProcessor(),
    )
    candidate = apply_price_warnings(matched.candidates)[0]
    assert candidate.pricing_blockers == []
    assert candidate.new_price == Decimal("909370")
    assert is_exportable(candidate) is True
