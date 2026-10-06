"""Plain persistence records returned by repositories.

These are independent of both SQLAlchemy ORM rows and Step 2 domain models.
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
    supplier_code: str
    pioneers_code: str
    mapping_type: str
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
