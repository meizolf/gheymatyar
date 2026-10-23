"""Unit tests for confirmed Rial sale policy and printed-price basis."""

from __future__ import annotations

from decimal import Decimal

from gheymatyar.domain.sale_policy import (
    PIONEERS_SALE_CURRENCY,
    PRICE_BASIS_PRINTED,
    TOMAN_TO_RIAL,
)
from gheymatyar.services.price_validation import compatibility_blockers, normalize_sale_policy


def test_pioneers_sale_currency_is_rial() -> None:
    assert PIONEERS_SALE_CURRENCY == "rial"
    assert TOMAN_TO_RIAL == Decimal("10")
    currency, basis = normalize_sale_policy("rial", "piece")
    assert currency == "rial"
    assert basis == "piece"


def test_printed_basis_skips_unit_blocker_when_currency_matches() -> None:
    blockers = compatibility_blockers(
        source_unit=None,
        price_basis=PRICE_BASIS_PRINTED,
        source_currency="rial",
        target_unit=None,
        confirmed_currency="rial",
        confirmed_basis=None,
    )
    assert blockers == []


def test_listed_basis_still_blocks() -> None:
    blockers = compatibility_blockers(
        source_unit=None,
        price_basis="listed",
        source_currency="rial",
        target_unit=None,
        confirmed_currency="rial",
        confirmed_basis="piece",
    )
    assert any("supplier price basis" in item for item in blockers)


def test_cleared_currency_still_blocks_printed_rows() -> None:
    blockers = compatibility_blockers(
        source_unit=None,
        price_basis=PRICE_BASIS_PRINTED,
        source_currency="rial",
        target_unit=None,
        confirmed_currency="",
        confirmed_basis=None,
    )
    assert any("sale currency" in item for item in blockers)
