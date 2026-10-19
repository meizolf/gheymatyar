"""Name normalization unit tests."""

from __future__ import annotations

from gheymatyar.services.name_normalization import (
    name_similarity,
    normalize_digits,
    normalize_product_name,
)


def test_persian_arabic_letter_folding() -> None:
    assert normalize_product_name("لوله كشي") == normalize_product_name("لوله کشی")


def test_digit_normalization() -> None:
    assert normalize_digits("۱۲۳۴۵") == "12345"
    assert normalize_product_name("لوله ۲۰") == normalize_product_name("لوله 20")


def test_whitespace_and_tatweel() -> None:
    # Tatweel inside a word is stripped (as in Pioneers header نـــام).
    assert normalize_product_name("نـــام کالا") == normalize_product_name("نام کالا")
    assert normalize_product_name("  اذین   لوله   20 ") == normalize_product_name(
        "اذین لوله 20"
    )


def test_alieh_spelling_fix() -> None:
    assert "لایه" in normalize_product_name("لوله سه الیه 20")


def test_example_supplier_vs_pioneers_similarity() -> None:
    supplier = "لوله PP-RCT سه لایه سایز 20"
    pioneers = "پارس پلاست لوله سه لایه 20"
    assert name_similarity(supplier, pioneers) > 0.3


def test_exact_normalized_match() -> None:
    a = "اذین لوله سه لایه 20"
    b = "اذین  لوله   سه  لایه ۲۰"
    assert normalize_product_name(a) == normalize_product_name(b)
