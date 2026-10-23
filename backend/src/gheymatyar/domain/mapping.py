"""Product mapping domain model (name-based, supplier-specific)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationInfo, field_validator

from gheymatyar.domain.enums import MappingType
from gheymatyar.domain.parsing import normalize_optional_str, require_non_empty_str


class ProductMapping(BaseModel):
    """Confirmed link between one supplier variant and a Pioneers product."""

    model_config = ConfigDict(frozen=True, str_strip_whitespace=True)

    supplier_id: str
    supplier_name_raw: str
    supplier_name_normalized: str
    pioneers_name_raw: str
    pioneers_name_normalized: str
    pioneers_code: str | None = None
    supplier_code: str | None = None
    unit_normalized: str | None = None
    legacy_unscoped: bool = False
    mapping_type: MappingType = MappingType.MANUAL

    @field_validator(
        "supplier_id",
        "supplier_name_raw",
        "supplier_name_normalized",
        "pioneers_name_raw",
        "pioneers_name_normalized",
        mode="before",
    )
    @classmethod
    def _required_text(cls, value: Any, info: ValidationInfo) -> str:
        return require_non_empty_str(value, info.field_name)

    @field_validator("pioneers_code", mode="before")
    @classmethod
    def _optional_code(cls, value: Any) -> str | None:
        return normalize_optional_str(value, "pioneers_code")
