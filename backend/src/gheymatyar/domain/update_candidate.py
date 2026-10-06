"""Update candidate domain model."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator

from gheymatyar.domain.enums import MappingType, MatchStatus
from gheymatyar.domain.parsing import (
    normalize_optional_str,
    require_non_empty_str,
    to_decimal,
)


class UpdateCandidate(BaseModel):
    """A proposed price change derived from supplier vs Pioneers data."""

    model_config = ConfigDict(frozen=True, str_strip_whitespace=True)

    pioneers_code: str
    pioneers_name: str
    supplier_code: str | None = None
    supplier_name: str
    old_price: Decimal
    new_price: Decimal
    absolute_change: Decimal
    # Null when percentage cannot be calculated safely (e.g. old_price == 0).
    percentage_change: Decimal | None = None
    # Reuses MappingType so match provenance matches mapping semantics.
    match_type: MappingType
    status: MatchStatus
    warnings: list[str] = Field(default_factory=list)

    @field_validator("pioneers_code", "pioneers_name", "supplier_name", mode="before")
    @classmethod
    def _required_text(cls, value: Any, info: ValidationInfo) -> str:
        return require_non_empty_str(value, info.field_name)

    @field_validator("supplier_code", mode="before")
    @classmethod
    def _optional_supplier_code(cls, value: Any) -> str | None:
        return normalize_optional_str(value, "supplier_code")

    @field_validator("old_price", "new_price", "absolute_change", mode="before")
    @classmethod
    def _required_decimals(cls, value: Any) -> Decimal:
        return to_decimal(value)

    @field_validator("percentage_change", mode="before")
    @classmethod
    def _optional_percentage(cls, value: Any) -> Decimal | None:
        if value is None:
            return None
        if isinstance(value, str) and not value.strip():
            return None
        return to_decimal(value)

    @field_validator("warnings", mode="before")
    @classmethod
    def _warnings(cls, value: Any) -> list[str]:
        if value is None:
            return []
        if not isinstance(value, list):
            raise ValueError("warnings must be a list of strings")
        cleaned: list[str] = []
        for item in value:
            if not isinstance(item, str):
                raise ValueError("warnings must be a list of strings")
            text = item.strip()
            if text:
                cleaned.append(text)
        return cleaned
