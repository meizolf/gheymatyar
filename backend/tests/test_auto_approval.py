"""Changes within the increase/decrease warning thresholds are approved automatically."""

from __future__ import annotations

from decimal import Decimal

import pytest

from gheymatyar.domain.enums import MatchStatus, ReviewDecision
from gheymatyar.domain.update_candidate import UpdateCandidate
from gheymatyar.services.price_validation import (
    PriceThresholds,
    apply_price_warnings,
    approval_state,
    is_exportable,
)

THRESHOLDS = PriceThresholds(increase=Decimal("50"), decrease=Decimal("20"))


def _row(new: str, *, old: str = "1000", decision=ReviewDecision.INCLUDE,
         status=MatchStatus.MATCHED, blockers=(), row: int = 2) -> UpdateCandidate:
    old_price, new_price = Decimal(old), Decimal(new)
    percent = None if old_price == 0 else (new_price - old_price) / old_price * 100
    return UpdateCandidate(
        candidate_id="c", row_number=row, pioneers_code="100", pioneers_name="کالا",
        supplier_name="کالا", old_price=old_price, new_price=new_price,
        absolute_change=new_price - old_price, percentage_change=percent,
        status=status, review_decision=decision, pricing_blockers=list(blockers),
        warnings=list(blockers), source_currency="rial", price_basis="printed",
    )


def _checked(candidate: UpdateCandidate, conflicted=frozenset()) -> UpdateCandidate:
    return apply_price_warnings(
        [candidate], thresholds=THRESHOLDS, conflicted_row_numbers=conflicted
    )[0]


@pytest.mark.parametrize(
    ("label", "candidate", "state", "exported"),
    [
        ("8% up", _row("1080"), "auto", True),
        ("exactly +50%", _row("1500"), "auto", True),
        ("just over +50%", _row("1501"), "required", False),
        ("exactly -20%", _row("800"), "auto", True),
        ("just under -20%", _row("799"), "required", False),
        ("30% down", _row("700"), "required", False),
        ("70% up", _row("1700"), "required", False),
        ("70% up, approved", _row("1700", decision=ReviewDecision.APPROVE), "manual", True),
        ("previous price zero", _row("500", old="0"), "required", False),
        ("same price", _row("1000"), "unchanged", False),
        ("user excluded", _row("1080", decision=ReviewDecision.EXCLUDE), "excluded", False),
        ("blocker", _row("1080", blockers=["price basis: unresolved"]), "blocked", False),
        ("blocker, approved", _row("1080", decision=ReviewDecision.APPROVE,
                                   blockers=["price basis: unresolved"]), "blocked", False),
        ("ambiguous match", _row("1080", status=MatchStatus.AMBIGUOUS), None, False),
    ],
)
def test_threshold_decides_automatic_or_manual_approval(
    label: str, candidate: UpdateCandidate, state: str | None, exported: bool
) -> None:
    checked = _checked(candidate)
    assert approval_state(checked) == state, label
    assert is_exportable(checked) is exported, label


def test_duplicate_pioneers_code_stays_blocked_even_when_approved() -> None:
    for decision in (ReviewDecision.INCLUDE, ReviewDecision.APPROVE):
        checked = _checked(_row("1080", decision=decision), conflicted=frozenset({2}))
        assert approval_state(checked) == "blocked"
        assert not is_exportable(checked)


def test_rechecks_neither_duplicate_warnings_nor_turn_into_exclusions() -> None:
    once = _checked(_row("1700"))
    twice = _checked(_checked(once))
    assert twice.warnings == once.warnings and len(once.warnings) == 1
    assert twice.review_decision is ReviewDecision.INCLUDE  # still the user's call
    # A higher threshold later approves the same untouched row automatically.
    relaxed = apply_price_warnings(
        [twice], thresholds=PriceThresholds(Decimal("80"), Decimal("20"))
    )[0]
    assert relaxed.warnings == [] and approval_state(relaxed) == "auto"
