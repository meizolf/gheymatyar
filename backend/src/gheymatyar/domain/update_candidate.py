"""Update candidate domain model."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator

from gheymatyar.domain.enums import MappingType, MatchStatus, ReviewDecision
from gheymatyar.domain.parsing import (
    normalize_optional_str,
    require_non_empty_str,
    to_decimal,
)


class UpdateCandidate(BaseModel):
    """A proposed price change derived from supplier vs Pioneers data."""

    model_config = ConfigDict(frozen=True, str_strip_whitespace=True)

    candidate_id: str
    row_number: int | None = None
    pioneers_code: str | None = None
    pioneers_name: str | None = None
    supplier_code: str | None = None
    supplier_name: str
    old_price: Decimal | None = None
    new_price: Decimal | None = None
    absolute_change: Decimal | None = None
    percentage_change: Decimal | None = None
    match_type: MappingType | None = None
    status: MatchStatus
    review_decision: ReviewDecision = ReviewDecision.INCLUDE
    warnings: list[str] = Field(default_factory=list)
    suggestions: list[dict[str, Any]] = Field(default_factory=list)

    @field_validator("candidate_id", "supplier_name", mode="before")
    @classmethod
    def _required_text(cls, value: Any, info: ValidationInfo) -> str:
        return require_non_empty_str(value, info.field_name)

    @field_validator("pioneers_code", "pioneers_name", "supplier_code", mode="before")
    @classmethod
    def _optional_text(cls, value: Any, info: ValidationInfo) -> str | None:
        return normalize_optional_str(value, info.field_name)

    @field_validator(
        "old_price",
        "new_price",
        "absolute_change",
        "percentage_change",
        mode="before",
    )
    @classmethod
    def _optional_decimals(cls, value: Any) -> Decimal | None:
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

    @field_validator("suggestions", mode="before")
    @classmethod
    def _suggestions(cls, value: Any) -> list[dict[str, Any]]:
        if value is None:
            return []
        if not isinstance(value, list):
            raise ValueError("suggestions must be a list")
        return list(value)
