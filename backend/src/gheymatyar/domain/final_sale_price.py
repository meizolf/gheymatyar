"""Resolved final-sale-price update written into the current Pioneers Excel."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationInfo, field_validator

from gheymatyar.domain.parsing import (
    normalize_optional_str,
    require_non_empty_str,
    require_positive_whole_price,
)


class FinalSalePriceUpdate(BaseModel):
    """One product already resolved against the current Pioneers workbook.

    ``row_number`` is the physical target in that workbook. ``pioneers_name``
    is checked against the row before anything is written. ``pioneers_code``
    is an optional extra check. ``final_sale_price`` is written only into
    ``نرخ فروش اصلی``.
    """

    model_config = ConfigDict(frozen=True)

    row_number: int
    pioneers_name: str
    pioneers_code: str | None = None
    final_sale_price: Decimal

    @field_validator("row_number", mode="before")
    @classmethod
    def _row_number(cls, value: Any) -> int:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError("row_number must be an integer")
        if value < 2:
            raise ValueError("row_number must be a product row below the header")
        return value

    @field_validator("pioneers_name", mode="before")
    @classmethod
    def _name(cls, value: Any, info: ValidationInfo) -> str:
        return require_non_empty_str(value, info.field_name)

    @field_validator("pioneers_code", mode="before")
    @classmethod
    def _code(cls, value: Any) -> str | None:
        return normalize_optional_str(value, "pioneers_code")

    @field_validator("final_sale_price", mode="before")
    @classmethod
    def _price(cls, value: Any, info: ValidationInfo) -> Decimal:
        return require_positive_whole_price(value, info.field_name)
