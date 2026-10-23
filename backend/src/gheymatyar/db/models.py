"""SQLAlchemy ORM table definitions for GheymatYar persistence.

These models are persistence-only. Domain value objects in
``gheymatyar.domain`` must not inherit from or depend on these classes.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Any, Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    TypeDecorator,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utc_now() -> datetime:
    """Timezone-aware UTC timestamp for ORM column defaults."""
    return datetime.now(timezone.utc)


class UTCDateTime(TypeDecorator):
    """Store datetimes as UTC; restore tzinfo on read (SQLite strips it)."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(
        self, value: datetime | None, dialect: Any
    ) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    def process_result_value(
        self, value: datetime | None, dialect: Any
    ) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


class DecimalAsText(TypeDecorator):
    """Persist ``Decimal`` as TEXT so SQLite never coerces via float.

    SQLAlchemy's ``Numeric`` type is backed by REAL on SQLite, which silently
    rounds large fractional values. Storing the exact decimal string avoids that.
    """

    impl = Text
    cache_ok = True

    def process_bind_param(self, value: Any, dialect: Any) -> str | None:
        if value is None:
            return None
        if isinstance(value, float):
            raise TypeError("monetary values must be Decimal, not float")
        if isinstance(value, Decimal):
            amount = value
        else:
            amount = Decimal(str(value))
        if not amount.is_finite():
            raise ValueError(f"non-finite decimal value is not allowed: {amount!r}")
        # Fixed-point string avoids scientific notation for large magnitudes.
        return format(amount, "f")

    def process_result_value(self, value: Any, dialect: Any) -> Decimal | None:
        if value is None:
            return None
        return Decimal(str(value))


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


class JobStatus(str, Enum):
    """Persistence-safe job lifecycle values (no workflow behavior yet)."""

    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


# TEXT-backed Decimals — not Numeric/REAL — so precision survives SQLite.
_MONEY = DecimalAsText()
_PERCENT = DecimalAsText()


class SupplierRow(Base):
    __tablename__ = "suppliers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    parser_type: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        nullable=False,
        default=utc_now,
    )

    mappings: Mapped[list[ProductMappingRow]] = relationship(back_populates="supplier")
    decisions: Mapped[list[SupplierProductDecisionRow]] = relationship(
        back_populates="supplier"
    )
    jobs: Mapped[list[JobRow]] = relationship(back_populates="supplier")


class ProductMappingRow(Base):
    """Supplier-specific confirmed mappings, one per product variant.

    Identity is the supplier plus normalized name, supplier code, and unit.
    Excel row numbers are never stored. ``pioneers_code`` is an optional
    target reference and is null when the confirmed Pioneers row has no code.
    ``legacy_unscoped`` rows were saved before variants were distinguished and
    apply only when the current upload has a single product with that name.
    """

    __tablename__ = "product_mappings"
    __table_args__ = (
        UniqueConstraint(
            "supplier_id",
            "identity_key",
            name="uq_product_mappings_supplier_variant",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    supplier_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("suppliers.id", ondelete="CASCADE"),
        nullable=False,
    )
    identity_key: Mapped[str] = mapped_column(Text, nullable=False)
    supplier_name_raw: Mapped[str] = mapped_column(Text, nullable=False)
    supplier_name_normalized: Mapped[str] = mapped_column(String(512), nullable=False)
    supplier_code: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    unit_normalized: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    legacy_unscoped: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    pioneers_name_raw: Mapped[str] = mapped_column(Text, nullable=False)
    pioneers_name_normalized: Mapped[str] = mapped_column(String(512), nullable=False)
    pioneers_code: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    # Values align with domain MappingType: SAVED_MAPPING / EXACT_NAME / MANUAL
    mapping_type: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        nullable=False,
        default=utc_now,
    )
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
    )

    supplier: Mapped[SupplierRow] = relationship(back_populates="mappings")


class SupplierProductDecisionRow(Base):
    """Persistent ignore/restore decision for one supplier product identity.

    Identity is the supplier plus a stable key (normalized name, code, unit).
    Session ids, PDF filenames, and Excel row numbers are not stored.
    ``IGNORED`` is a soft-delete: supplier and Pioneers rows are never removed.
    ``ACTIVE`` records an explicit restore.
    """

    __tablename__ = "supplier_product_decisions"
    __table_args__ = (
        UniqueConstraint(
            "supplier_id",
            "identity_key",
            name="uq_supplier_product_decisions_identity",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    supplier_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("suppliers.id", ondelete="CASCADE"),
        nullable=False,
    )
    identity_key: Mapped[str] = mapped_column(Text, nullable=False)
    supplier_name_raw: Mapped[str] = mapped_column(Text, nullable=False)
    supplier_name_normalized: Mapped[str] = mapped_column(String(512), nullable=False)
    supplier_code: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    unit_normalized: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    # IGNORED (soft-delete) or ACTIVE (restored / explicitly not ignored)
    decision: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        nullable=False,
        default=utc_now,
    )
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
    )

    supplier: Mapped[SupplierRow] = relationship(back_populates="decisions")


class JobRow(Base):
    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    supplier_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("suppliers.id", ondelete="CASCADE"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        nullable=False,
        default=utc_now,
    )
    source_filename: Mapped[str] = mapped_column(String(512), nullable=False)
    pioneers_filename: Mapped[str] = mapped_column(String(512), nullable=False)
    matched_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    unmatched_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    warning_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(32), nullable=False)

    supplier: Mapped[SupplierRow] = relationship(back_populates="jobs")
    items: Mapped[list[JobItemRow]] = relationship(
        back_populates="job",
        cascade="all, delete-orphan",
    )


class JobItemRow(Base):
    __tablename__ = "job_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("jobs.id", ondelete="CASCADE"),
        nullable=False,
    )
    supplier_code: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    pioneers_code: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    old_price: Mapped[Optional[Decimal]] = mapped_column(_MONEY, nullable=True)
    new_price: Mapped[Optional[Decimal]] = mapped_column(_MONEY, nullable=True)
    percentage_change: Mapped[Optional[Decimal]] = mapped_column(_PERCENT, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    warning: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    job: Mapped[JobRow] = relationship(back_populates="items")


class SettingRow(Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(255), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)
