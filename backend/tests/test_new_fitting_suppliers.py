"""Kaveh Gostar, Iranian, and Zaco/foreign fitting price lists.

Each PDF is parsed once per module. Expected prices were read off the
rendered pages, one row/column intersection at a time.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from gheymatyar.suppliers.galvanized_fittings import (
    IranianFittingsProcessor,
    ZacoForeignFittingsProcessor,
)
from gheymatyar.suppliers.kaveh_gostar import KavehGostarProcessor
from gheymatyar.suppliers.registry import get_default_registry

from .conftest import IRANIAN_PDF, KAVEH_TEXT_PDF, ZACO_PDF

IR = "اتصالات ایرانی آبکاری سرد "
ZA = "اتصالات زاکو و خارجی "
KG = "کاوه گستر "
SUPPLIERS = {
    "iranian_fittings": (IranianFittingsProcessor, IRANIAN_PDF, 127),
    "zaco_foreign_fittings": (ZacoForeignFittingsProcessor, ZACO_PDF, 280),
    "kaveh_gostar": (KavehGostarProcessor, KAVEH_TEXT_PDF, 540),
}


@pytest.fixture(scope="module")
def parsed():
    return {key: proc().parse_pdf(pdf) for key, (proc, pdf, _count) in SUPPLIERS.items()}


@pytest.mark.parametrize(
    ("supplier", "name", "rial"),
    [
        ("iranian_fittings", IR + 'زانو سایز 1/2"', 810_000),
        ("iranian_fittings", IR + 'بوشن جوشی سایز 4"', 11_200_000),
        ("iranian_fittings", IR + 'مهره سفید سایز 4"', 35_400_000),
        # Reducer rows: the row's size × the column's size, larger first.
        ("iranian_fittings", IR + 'تبدیل سایز 1 1/4"×1"', 1_320_000),
        ("iranian_fittings", IR + 'تبدیل سایز 1 1/4"×1/2"', 1_500_000),
        ("iranian_fittings", IR + 'تبدیل سایز 4"×3"', 12_710_000),
        ("iranian_fittings", IR + 'مهره طلایی سایز 2"', 11_000_000),
        ("iranian_fittings", IR + 'روپیچ کوتاه سایز 1/2"', 620_000),
        ("zaco_foreign_fittings", ZA + 'زانو سایز 1/2"', 900_000),
        ("zaco_foreign_fittings", ZA + 'درپوش زاکو سایز 3/4"', 490_000),
        ("zaco_foreign_fittings", ZA + 'زانو 45 درجه سایز 4"', 24_100_000),
        ("zaco_foreign_fittings", ZA + 'تبدیل سایز 4"×3"', 13_700_000),
        # The three-product rows: each label with its own price cell.
        ("zaco_foreign_fittings", ZA + 'بوشن سایز 3"×2"', 9_750_000),
        ("zaco_foreign_fittings", ZA + 'تبدیل سیاه سایز 1"×3/4"', 770_000),
        ("zaco_foreign_fittings", ZA + "لنگی دیواری", 500_000),
        ("zaco_foreign_fittings", ZA + 'مغزی سایز 3/4"×1/2"', 1_030_000),
        # Under the «اتصالات سیاه» divider.
        ("zaco_foreign_fittings", ZA + 'مهره سیاه سایز 4"', 33_000_000),
        ("zaco_foreign_fittings", ZA + 'بوشن سیاه سایز 1/2"', 700_000),
        ("kaveh_gostar", KG + "اتصال نر سایز 20×1/2", 700_000),
        ("kaveh_gostar", KG + "اتصال ماده سایز 40×1 1/4", 3_500_000),  # printed 11/4
        # Same title on the threaded and irrigation pages: section in the name.
        ("kaveh_gostar", KG + "زانو پیچی سایز 20×20", 1_500_000),
        ("kaveh_gostar", KG + "زانو آبیاری سایز 16", 30_000),
        ("kaveh_gostar", KG + "کمربند سایز 20×1/2", 800_000),
        ("kaveh_gostar", KG + "کمربند دوسرنافی سایز 315×4", 54_000_000),
        ("kaveh_gostar", KG + "کمربند ناف برنجی سایز 25×1/2", 3_200_000),
        # One merged size cell over six lengths.
        ("kaveh_gostar", KG + "رایزر پلیمری سایز 1 1/2 طول 100 cm", 15_000_000),
        ("kaveh_gostar", KG + "اورینگ کمربند سایز 63×1 1/4", 300_000),
        ("kaveh_gostar", KG + "مهره سایز 6", 40_000),
    ],
)
def test_row_and_column_prices(parsed, supplier, name, rial) -> None:
    prices = {item.supplier_name: item.price for item in parsed[supplier].items}
    assert prices.get(name) == Decimal(rial), name


@pytest.mark.parametrize("supplier", list(SUPPLIERS))
def test_counts_rial_and_unique_names(parsed, supplier) -> None:
    result = parsed[supplier]
    names = [item.supplier_name for item in result.items]
    assert len(names) == SUPPLIERS[supplier][2]
    assert len(names) == len(set(names))
    assert all(item.price > 0 for item in result.items)
    assert {item.raw_values["currency"] for item in result.items} == {"rial"}
    assert {item.raw_values["price_basis"] for item in result.items} == {"printed"}
    assert get_default_registry().detect(SUPPLIERS[supplier][1]).detected_supplier_id == supplier


def test_unpriced_cells_are_skipped_not_guessed(parsed) -> None:
    kaveh = parsed["kaveh_gostar"]
    keys = [i.supplier_name for i in kaveh.items if "کلید شیرخودکار" in i.supplier_name]
    assert keys == [KG + "کلید شیرخودکار سایز 3/4", KG + "کلید شیرخودکار سایز 1"]  # «*» rows dropped
    assert any("'*'" in w for w in kaveh.warnings)
    # Pack counts are reference only.
    elbow = next(i for i in kaveh.items if i.supplier_name == KG + "اتصال نر سایز 20×1/2")
    assert elbow.raw_values["package_count"] == "150" and elbow.price == Decimal("700000")
    iranian = {i.supplier_name for i in parsed["iranian_fittings"].items}
    assert IR + 'زانو سایز 4"' not in iranian  # empty cell
