"""Product mapping domain model."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationInfo, field_validator

from gheymatyar.domain.enums import MappingType
from gheymatyar.domain.parsing import require_non_empty_str


class ProductMapping(BaseModel):
    """Explicit link between a supplier SKU and a Pioneers product code."""

    model_config = ConfigDict(frozen=True, str_strip_whitespace=True)

    supplier_id: str
    supplier_code: str
    pioneers_code: str
    mapping_type: MappingType

    @field_validator("supplier_id", "supplier_code", "pioneers_code", mode="before")
    @classmethod
    def _required_text(cls, value: Any, info: ValidationInfo) -> str:
        return require_non_empty_str(value, info.field_name)
