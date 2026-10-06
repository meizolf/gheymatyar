"""Shared Decimal parsing helpers for domain models.

Money fields use ``decimal.Decimal`` (not binary float) so values keep
exact decimal places as provided. Callers should prefer ``Decimal`` or
decimal strings; ``float`` input is accepted via ``Decimal(str(value))``
but may already have lost precision before reaching the model.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any


def require_non_empty_str(value: Any, field_name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string")
    stripped = value.strip()
    if not stripped:
        raise ValueError(f"{field_name} must be a non-empty string")
    return stripped


def normalize_optional_str(value: Any, field_name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string or null")
    stripped = value.strip()
    return stripped or None


def _reject_non_finite(amount: Decimal) -> Decimal:
    """Reject NaN / sNaN / Infinity so callers get ValueError, not InvalidOperation."""
    if not amount.is_finite():
        raise ValueError(f"non-finite decimal value is not allowed: {amount!r}")
    return amount


def to_decimal(value: Any) -> Decimal:
    """Parse a Decimal without silent rounding of Decimal inputs."""
    if isinstance(value, Decimal):
        return _reject_non_finite(value)
    if isinstance(value, bool):
        # bool is a subclass of int; reject explicitly.
        raise ValueError("boolean is not a valid decimal")
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        return _reject_non_finite(Decimal(str(value)))
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            raise ValueError("empty string is not a valid decimal")
        try:
            return _reject_non_finite(Decimal(stripped))
        except InvalidOperation as exc:
            raise ValueError(f"invalid decimal value: {value!r}") from exc
    raise ValueError(f"unsupported decimal type: {type(value).__name__}")


def optional_decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, str) and not value.strip():
        return None
    return to_decimal(value)


def require_positive_decimal(value: Any, field_name: str) -> Decimal:
    amount = to_decimal(value)
    if amount <= 0:
        raise ValueError(f"{field_name} must be greater than zero")
    return amount
