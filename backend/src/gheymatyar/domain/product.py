"""Pioneers product domain model."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator

from gheymatyar.domain.parsing import (
    normalize_optional_str,
    optional_decimal,
    require_non_empty_str,
)


class PioneersProduct(BaseModel):
    """A product row imported from a Pioneers Excel export.

    ``name`` is required. ``code`` is optional — used as a secondary safety
    check during export, not as the primary matching key.
    """

    model_config = ConfigDict(frozen=True, str_strip_whitespace=True)

    row_number: int = Field(..., ge=1, description="Original Excel row number")
    name: str
    code: str | None = None
    barcode: str | None = None
    unit: str | None = None
    sale_price: Decimal | None = None
    last_purchase_price: Decimal | None = None
    consumer_price: Decimal | None = None
    colleague_price: Decimal | None = None
    # Arbitrary source-row keys (column letters, indexes, headers, etc.).
    raw_values: dict[Any, Any] = Field(default_factory=dict)

    @field_validator("name", mode="before")
    @classmethod
    def _required_name(cls, value: Any, info: ValidationInfo) -> str:
        return require_non_empty_str(value, info.field_name)

    @field_validator("code", "barcode", "unit", mode="before")
    @classmethod
    def _optional_text(cls, value: Any, info: ValidationInfo) -> str | None:
        return normalize_optional_str(value, info.field_name)

    @field_validator(
        "sale_price",
        "last_purchase_price",
        "consumer_price",
        "colleague_price",
        mode="before",
    )
    @classmethod
    def _optional_prices(cls, value: Any) -> Decimal | None:
        return optional_decimal(value)
