"""Azin Pipe supplier PDF extraction tests."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from gheymatyar.suppliers.azin_pipe import AzinPipeProcessor, fix_reversed_persian
from gheymatyar.suppliers.errors import SupplierPdfError, UnsupportedSupplierError
from gheymatyar.suppliers.registry import get_default_registry


def test_fix_reversed_persian_category() -> None:
    assert fix_reversed_persian("نشوب") == "بوشن"
    assert "لایه" in fix_reversed_persian("هیلا هس هلول")


def test_azin_pdf_extracts_products(azin_pdf: Path) -> None:
    result = AzinPipeProcessor().parse_pdf(azin_pdf)
    assert result.supplier_key == "azin_pipe"
    assert len(result.items) >= 200
    codes = {i.supplier_code for i in result.items}
    assert "819121020" in codes  # لوله سه لایه 20
    assert "819161020" in codes  # لوله تک لایه 20
    assert "855321101" in codes  # بوشن 20

    three_layer = next(i for i in result.items if i.supplier_code == "819121020")
    assert three_layer.price == Decimal("1987040")
    assert "سه لایه" in three_layer.supplier_name or "سه لایه" in three_layer.supplier_name.replace(
        "الیه", "لایه"
    )
    assert "20" in three_layer.supplier_name
    assert three_layer.supplier_name.startswith("اذین")


def test_azin_prices_are_positive_decimals(azin_pdf: Path) -> None:
    result = AzinPipeProcessor().parse_pdf(azin_pdf)
    for item in result.items:
        assert isinstance(item.price, Decimal)
        assert item.price > 0
        assert item.price == item.price.to_integral_value()


def test_azin_direct_replacement_pricing(azin_pdf: Path) -> None:
    processor = AzinPipeProcessor()
    result = processor.parse_pdf(azin_pdf)
    item = result.items[0]
    assert processor.calculate_final_sale_price(item) == item.price


def test_registry_lists_azin() -> None:
    registry = get_default_registry()
    keys = registry.keys()
    assert "azin_pipe" in keys
    info = registry.list_suppliers()
    assert any(s.key == "azin_pipe" for s in info)


def test_unsupported_supplier_raises() -> None:
    with pytest.raises(UnsupportedSupplierError):
        get_default_registry().get("unknown_brand")


def test_missing_pdf_raises(tmp_path: Path) -> None:
    with pytest.raises(SupplierPdfError):
        AzinPipeProcessor().parse_pdf(tmp_path / "missing.pdf")
