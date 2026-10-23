"""Plain persistence records returned by repositories.

These are independent of both SQLAlchemy ORM rows and domain models.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class SupplierRecord:
    id: int
    name: str
    parser_type: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class ProductMappingRecord:
    id: int
    supplier_id: int
    supplier_name_raw: str
    supplier_name_normalized: str
    pioneers_name_raw: str
    pioneers_name_normalized: str
    pioneers_code: str | None
    identity_key: str
    supplier_code: str | None
    unit_normalized: str | None
    legacy_unscoped: bool
    mapping_type: str
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class SupplierProductDecisionRecord:
    id: int
    supplier_id: int
    identity_key: str
    supplier_name_raw: str
    supplier_name_normalized: str
    supplier_code: str | None
    unit_normalized: str | None
    decision: str
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class JobRecord:
    id: int
    supplier_id: int
    created_at: datetime
    source_filename: str
    pioneers_filename: str
    matched_count: int
    unmatched_count: int
    warning_count: int
    status: str


@dataclass(frozen=True, slots=True)
class JobItemRecord:
    id: int
    job_id: int
    supplier_code: str | None
    pioneers_code: str | None
    old_price: Decimal | None
    new_price: Decimal | None
    percentage_change: Decimal | None
    status: str
    warning: str | None


@dataclass(frozen=True, slots=True)
class SettingRecord:
    key: str
    value: str
