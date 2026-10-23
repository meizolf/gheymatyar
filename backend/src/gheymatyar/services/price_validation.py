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
        for blocker in candidate.pricing_blockers:
            if blocker not in warnings:
                warnings.append(blocker)
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


_BASIS_PREFIX = "price basis:"
_CURRENCY_PREFIX = "sale currency:"

TARGET_BASIS_UNRESOLVED = (
    "price basis: Pioneers price basis is not on the workbook and was not confirmed; "
    "automatic export is blocked"
)
SOURCE_BASIS_UNRESOLVED = (
    "price basis: supplier price basis is not an explicit per-metre or per-piece price; "
    "automatic export is blocked until the unit is confirmed"
)
CURRENCY_UNRESOLVED = (
    "sale currency: Pioneers sale currency is not confirmed; "
    "no conversion was applied and automatic export is blocked"
)
SUPPLIER_CURRENCY_MISSING = (
    "sale currency: supplier currency was not stated; "
    "automatic export is blocked"
)


def _compatibility_text(text: str) -> bool:
    return text.startswith(_BASIS_PREFIX) or text.startswith(_CURRENCY_PREFIX)


def _classify_unit_text(unit: str) -> str | None:
    """Map an explicit unit label. Branch wins over metre in «شاخه 6 متری»."""
    compact = unit.replace(" ", "").replace("\u200c", "")
    if "شاخه" in unit:
        return "branch"
    if compact in {"متر", "مترطول", "m", "meter", "metre"} or compact.startswith("هرمتر"):
        return "meter"
    if compact in {"عدد", "دانه", "piece"}:
        return "piece"
    return None


def _classify_source(unit: str | None, basis: str | None) -> str:
    if unit and unit.strip():
        kind = _classify_unit_text(unit.strip())
        if kind:
            return kind
    if basis == "meter":
        return "meter"
    if basis == "piece":
        return "piece"
    # Confirmed printed Rial amount: use as-is (no length/carton multiply).
    if basis == "printed":
        return "printed"
    return "unresolved"


def _classify_target(unit: str | None, confirmed_basis: str | None) -> str:
    if unit and unit.strip():
        return _classify_unit_text(unit.strip()) or "unresolved"
    if confirmed_basis in {"meter", "piece"}:
        return confirmed_basis
    return "unresolved"


def _source_phrase(kind: str) -> str:
    return {"meter": "per metre", "piece": "per piece", "branch": "per branch"}[kind]


def _target_phrase(kind: str, unit: str | None) -> str:
    if unit and unit.strip():
        return repr(unit.strip())
    if kind == "meter":
        return "the confirmed per-metre sale basis"
    if kind == "piece":
        return "the confirmed per-piece sale basis"
    return "an unresolved unit"


def normalize_sale_policy(
    currency: str | None, basis: str | None
) -> tuple[str | None, str | None]:
    """Accept only an explicit Rial confirmation and an explicit metre or piece basis.

    Any other value, including a blank workbook, stays unconfirmed. Toman→Rial
    conversion belongs in the supplier processor (Decimal), not here. Metres are
    never converted into a branch unit.
    """
    confirmed_currency = (currency or "").strip().lower()
    confirmed_basis = (basis or "").strip().lower()
    return (
        confirmed_currency if confirmed_currency == "rial" else None,
        confirmed_basis if confirmed_basis in {"meter", "piece"} else None,
    )


def compatibility_blockers(
    *,
    source_unit: str | None,
    price_basis: str | None,
    source_currency: str | None,
    target_unit: str | None,
    confirmed_currency: str | None,
    confirmed_basis: str | None,
) -> list[str]:
    """Hard blocks for a matched row. Package quantities are never read."""
    currency, basis = normalize_sale_policy(confirmed_currency, confirmed_basis)
    blockers: list[str] = []
    source_kind = _classify_source(source_unit, price_basis)
    target_kind = _classify_target(target_unit, basis)
    if source_kind == "unresolved":
        blockers.append(SOURCE_BASIS_UNRESOLVED)
    elif source_kind == "printed":
        # Reliable price column identified; printed Rial amount is the sale price.
        pass
    elif target_kind == "unresolved":
        blockers.append(TARGET_BASIS_UNRESOLVED)
    elif source_kind != target_kind:
        blockers.append(
            "price basis: supplier price is "
            f"{_source_phrase(source_kind)} and the Pioneers unit is "
            f"{_target_phrase(target_kind, target_unit)}; "
            "no conversion was applied and automatic export is blocked"
        )

    stated = (source_currency or "").strip().lower()
    if not stated:
        blockers.append(SUPPLIER_CURRENCY_MISSING)
    elif currency is None:
        blockers.append(CURRENCY_UNRESOLVED)
    elif stated != currency:
        blockers.append(
            "sale currency: supplier currency "
            f"{stated} does not match confirmed Pioneers currency {currency}; "
            "no conversion was applied and automatic export is blocked"
        )
    return blockers


def apply_sale_compatibility(
    candidate: UpdateCandidate,
    *,
    target_unit: str | None,
    confirmed_currency: str | None,
    confirmed_basis: str | None,
) -> UpdateCandidate:
    """Replace currency/basis blockers. Other restrictions stay in place."""
    fresh = compatibility_blockers(
        source_unit=candidate.source_unit,
        price_basis=candidate.price_basis,
        source_currency=candidate.source_currency,
        target_unit=target_unit,
        confirmed_currency=confirmed_currency,
        confirmed_basis=confirmed_basis,
    )
    blockers = [item for item in candidate.pricing_blockers if not _compatibility_text(item)]
    for item in fresh:
        if item not in blockers:
            blockers.append(item)
    warnings = [item for item in candidate.warnings if not _compatibility_text(item)]
    for item in fresh:
        if item not in warnings:
            warnings.append(item)
    return candidate.model_copy(
        update={"pricing_blockers": blockers, "warnings": warnings}
    )


def is_exportable(candidate: UpdateCandidate) -> bool:
    """Whether a candidate may be written into the output Excel."""
    if candidate.status != MatchStatus.MATCHED:
        return False
    if candidate.row_number is None or not candidate.pioneers_name:
        return False
    if candidate.new_price is None or candidate.new_price <= 0:
        return False
    if candidate.pricing_blockers:
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
