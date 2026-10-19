"""Price-change validation and preview enrichment."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import AbstractSet, Sequence

from gheymatyar.domain.enums import MatchStatus, ReviewDecision
from gheymatyar.domain.final_sale_price import FinalSalePriceUpdate
from gheymatyar.domain.update_candidate import UpdateCandidate

DEFAULT_SUSPICIOUS_PERCENT_THRESHOLD = Decimal("30")

IDENTITY_CONFLICT_WARNING = (
    "duplicate Pioneers product code; cannot export until uniqueness is resolved"
)


def parse_suspicious_percent_threshold(raw: str | Decimal | None) -> Decimal:
    """Parse and validate a suspicious-change threshold percentage.

    Rejects empty, non-numeric, non-finite, zero, and negative values.
    """
    if raw is None:
        raise ValueError("suspicious_percent_threshold is required")
    if isinstance(raw, Decimal):
        value = raw
    else:
        text = str(raw).strip()
        if not text:
            raise ValueError("suspicious_percent_threshold must be a positive number")
        try:
            value = Decimal(text)
        except InvalidOperation as exc:
            raise ValueError(
                "suspicious_percent_threshold must be a positive number"
            ) from exc
    if not value.is_finite():
        raise ValueError("suspicious_percent_threshold must be a finite number")
    if value <= 0:
        raise ValueError("suspicious_percent_threshold must be greater than zero")
    return value


def resolve_suspicious_percent_threshold(
    *,
    request_value: str | Decimal | None = None,
    saved_value: str | None = None,
    default: Decimal = DEFAULT_SUSPICIOUS_PERCENT_THRESHOLD,
) -> Decimal:
    """Resolve threshold: request override → saved setting → default."""
    if request_value is not None and str(request_value).strip() != "":
        return parse_suspicious_percent_threshold(request_value)
    if saved_value is not None and str(saved_value).strip() != "":
        return parse_suspicious_percent_threshold(saved_value)
    return default


def apply_price_warnings(
    candidates: Sequence[UpdateCandidate],
    *,
    suspicious_percent_threshold: Decimal = DEFAULT_SUSPICIOUS_PERCENT_THRESHOLD,
    conflicted_row_numbers: AbstractSet[int] | None = None,
) -> list[UpdateCandidate]:
    """Return candidates with validation warnings attached (immutable copies)."""
    conflicted = conflicted_row_numbers or frozenset()
    enriched: list[UpdateCandidate] = []
    for candidate in candidates:
        warnings = [
            w for w in candidate.warnings if w != IDENTITY_CONFLICT_WARNING
        ]
        if (
            candidate.row_number is not None
            and candidate.row_number in conflicted
            and candidate.status == MatchStatus.MATCHED
        ):
            warnings.append(IDENTITY_CONFLICT_WARNING)
        if candidate.new_price is not None and candidate.new_price <= 0:
            warnings.append("final sale price must be greater than zero")
        if (
            candidate.status == MatchStatus.MATCHED
            and candidate.percentage_change is not None
            and abs(candidate.percentage_change) > suspicious_percent_threshold
        ):
            warnings.append(
                f"price change {candidate.percentage_change:.2f}% exceeds "
                f"{suspicious_percent_threshold}% threshold"
            )
        if (
            candidate.status == MatchStatus.MATCHED
            and candidate.old_price == 0
            and candidate.new_price is not None
            and candidate.new_price > 0
        ):
            warnings.append("previous sale price was zero; percentage change undefined")

        # Suspicious matched rows default to EXCLUDE until explicitly approved.
        # Identity conflicts stay non-exportable even if APPROVE is attempted later.
        decision = candidate.review_decision
        if (
            candidate.status == MatchStatus.MATCHED
            and warnings
            and decision == ReviewDecision.INCLUDE
        ):
            decision = ReviewDecision.EXCLUDE

        enriched.append(
            candidate.model_copy(
                update={"warnings": warnings, "review_decision": decision}
            )
        )
    return enriched


def is_exportable(candidate: UpdateCandidate) -> bool:
    """Whether a candidate may be written into the output Excel."""
    if candidate.status != MatchStatus.MATCHED:
        return False
    if candidate.row_number is None or not candidate.pioneers_name:
        return False
    if candidate.new_price is None or candidate.new_price <= 0:
        return False
    if IDENTITY_CONFLICT_WARNING in candidate.warnings:
        return False
    if candidate.review_decision == ReviewDecision.EXCLUDE:
        return False
    soft_warnings = [
        w for w in candidate.warnings if w != IDENTITY_CONFLICT_WARNING
    ]
    if soft_warnings and candidate.review_decision != ReviewDecision.APPROVE:
        return False
    if candidate.review_decision in {ReviewDecision.INCLUDE, ReviewDecision.APPROVE}:
        return True
    return False


def to_final_sale_updates(
    candidates: Sequence[UpdateCandidate],
) -> list[FinalSalePriceUpdate]:
    """Build writer payloads from exportable candidates. All-or-nothing caller."""
    updates: list[FinalSalePriceUpdate] = []
    for candidate in candidates:
        if not is_exportable(candidate):
            continue
        assert candidate.row_number is not None
        assert candidate.pioneers_name is not None
        assert candidate.new_price is not None
        updates.append(
            FinalSalePriceUpdate(
                row_number=candidate.row_number,
                pioneers_name=candidate.pioneers_name,
                pioneers_code=candidate.pioneers_code,
                final_sale_price=candidate.new_price,
            )
        )
    return updates
