"""Supplier price item domain model."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator

from gheymatyar.domain.parsing import (
    normalize_optional_str,
    require_non_empty_str,
    require_positive_decimal,
)


class SupplierPriceItem(BaseModel):
    """A priced SKU from a supplier list or PDF."""

    model_config = ConfigDict(frozen=True, str_strip_whitespace=True)

    # Stable string id suitable for later persistence / foreign keys.
    supplier_id: str
    supplier_code: str | None = None
    supplier_name: str
    barcode: str | None = None
    price: Decimal
    unit: str | None = None
    # Arbitrary source-row keys (column letters, indexes, headers, etc.).
    raw_values: dict[Any, Any] = Field(default_factory=dict)

    @field_validator("supplier_id", "supplier_name", mode="before")
    @classmethod
    def _required_text(cls, value: Any, info: ValidationInfo) -> str:
        return require_non_empty_str(value, info.field_name)

    @field_validator("supplier_code", "barcode", "unit", mode="before")
    @classmethod
    def _optional_text(cls, value: Any, info: ValidationInfo) -> str | None:
        return normalize_optional_str(value, info.field_name)

    @field_validator("price", mode="before")
    @classmethod
    def _price(cls, value: Any) -> Decimal:
        return require_positive_decimal(value, "price")
