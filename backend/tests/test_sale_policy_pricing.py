"""Unit tests for the fixed Rial sale policy and printed-price basis."""

from __future__ import annotations

from decimal import Decimal

from gheymatyar.domain.sale_policy import (
    OBSOLETE_SETTING_KEYS,
    PIONEERS_SALE_CURRENCY,
    PRICE_BASIS_PRINTED,
    TOMAN_TO_RIAL,
)
from gheymatyar.services.price_validation import compatibility_blockers


def test_pioneers_sale_currency_is_rial_without_a_setting() -> None:
    assert PIONEERS_SALE_CURRENCY == "rial"
    assert TOMAN_TO_RIAL == Decimal("10")
    assert OBSOLETE_SETTING_KEYS == (
        "pioneers_sale_currency",
        "pioneers_sale_basis",
    )


def test_printed_basis_skips_unit_blocker_when_currency_is_rial() -> None:
    blockers = compatibility_blockers(
        source_unit=None,
        price_basis=PRICE_BASIS_PRINTED,
        source_currency="rial",
        target_unit=None,
    )
    assert blockers == []


def test_missing_workbook_unit_does_not_block_a_per_metre_price() -> None:
    blockers = compatibility_blockers(
        source_unit="متر",
        price_basis="meter",
        source_currency="rial",
        target_unit=None,
    )
    assert blockers == []


def test_listed_basis_still_blocks() -> None:
    blockers = compatibility_blockers(
        source_unit=None,
        price_basis="listed",
        source_currency="rial",
        target_unit=None,
    )
    assert any("supplier price basis" in item for item in blockers)


def test_non_rial_supplier_currency_still_blocks() -> None:
    blockers = compatibility_blockers(
        source_unit=None,
        price_basis=PRICE_BASIS_PRINTED,
        source_currency="toman",
        target_unit=None,
    )
    assert any("sale currency" in item for item in blockers)
