"""Monetary Decimal precision and SQLite foreign-key / session safety tests."""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError, StatementError
from sqlalchemy.orm import Session

from gheymatyar.db import Database
from gheymatyar.db.models import JobItemRow, JobRow, SupplierRow
from gheymatyar.domain import MappingType
from gheymatyar.repositories import (
    JobRepository,
    MappingRepository,
    SupplierRepository,
)
from gheymatyar.repositories._session import flush_or_rollback


def test_money_precision_survives_round_trip(session: Session) -> None:
    """Values unsafe as binary floats must round-trip as Decimal."""
    supplier_id = SupplierRepository(session).create(
        name="Money Co", parser_type="pdf"
    ).id
    jobs = JobRepository(session)
    job = jobs.create(
        supplier_id=supplier_id,
        source_filename="s.xlsx",
        pioneers_filename="p.xlsx",
    )

    # Classic binary-float problem values.
    old_price = Decimal("0.1") + Decimal("0.2")  # 0.3 exactly as Decimal
    new_price = Decimal("19.99")
    pct = Decimal("0.1")

    assert old_price == Decimal("0.3")
    # Contrast: the same expression as float is not exactly 0.3.
    assert (0.1 + 0.2) != 0.3

    jobs.add_item(
        job_id=job.id,
        supplier_code="SKU",
        pioneers_code="P1",
        old_price=old_price,
        new_price=new_price,
        percentage_change=pct,
        status="MATCHED",
    )
    session.commit()

    items = jobs.list_items(job.id)
    assert len(items) == 1
    assert isinstance(items[0].old_price, Decimal)
    assert isinstance(items[0].new_price, Decimal)
    assert items[0].old_price == Decimal("0.3")
    assert items[0].new_price == Decimal("19.99")
    assert items[0].percentage_change == Decimal("0.1")


def test_large_decimal_survives_fresh_session_reload(db: Database) -> None:
    """Large fractional Decimals must survive a full write → new session → read.

    SQLite REAL (SQLAlchemy Numeric) silently rounds values like this; TEXT
    storage must preserve them exactly.
    """
    awkward = Decimal("12345678901234.123456")
    job_id: int

    with db.session() as session:
        supplier_id = SupplierRepository(session).create(
            name="Precision Co", parser_type="pdf"
        ).id
        jobs = JobRepository(session)
        job = jobs.create(
            supplier_id=supplier_id,
            source_filename="s.xlsx",
            pioneers_filename="p.xlsx",
        )
        jobs.add_item(
            job_id=job.id,
            status="MATCHED",
            old_price=awkward,
            new_price=awkward,
            percentage_change=Decimal("1.234567"),
        )
        job_id = job.id

    with db.session() as session:
        items = JobRepository(session).list_items(job_id)
        assert len(items) == 1
        assert items[0].old_price == awkward
        assert items[0].new_price == awkward
        assert items[0].percentage_change == Decimal("1.234567")
        # Must not be the REAL-rounded corruption of this value.
        assert items[0].old_price != Decimal("12345678901234.123047")


def test_job_repository_rejects_float_prices(session: Session) -> None:
    supplier_id = SupplierRepository(session).create(
        name="Float Guard", parser_type="pdf"
    ).id
    jobs = JobRepository(session)
    job = jobs.create(
        supplier_id=supplier_id,
        source_filename="s.xlsx",
        pioneers_filename="p.xlsx",
    )
    with pytest.raises(TypeError, match="Decimal"):
        jobs.add_item(
            job_id=job.id,
            status="MATCHED",
            old_price=0.1,  # type: ignore[arg-type]
        )


@pytest.mark.parametrize(
    "bad",
    [
        Decimal("NaN"),
        Decimal("sNaN"),
        Decimal("Infinity"),
        Decimal("-Infinity"),
    ],
)
def test_job_repository_rejects_non_finite_decimals(
    session: Session, bad: Decimal
) -> None:
    supplier_id = SupplierRepository(session).create(
        name=f"NonFinite-{bad}", parser_type="pdf"
    ).id
    jobs = JobRepository(session)
    job = jobs.create(
        supplier_id=supplier_id,
        source_filename="s.xlsx",
        pioneers_filename="p.xlsx",
    )
    with pytest.raises(ValueError, match="finite"):
        jobs.add_item(job_id=job.id, status="MATCHED", old_price=bad)


def test_foreign_key_mapping_rejects_missing_supplier(session: Session) -> None:
    repo = MappingRepository(session)
    with pytest.raises(IntegrityError):
        repo.create(
            supplier_id=999_999,
            supplier_name_raw="لوله 20",
            pioneers_name_raw="اذین لوله 20",
            pioneers_code="100",
            mapping_type=MappingType.MANUAL,
        )


def test_foreign_key_job_rejects_missing_supplier(session: Session) -> None:
    repo = JobRepository(session)
    with pytest.raises(IntegrityError):
        repo.create(
            supplier_id=999_999,
            source_filename="s.xlsx",
            pioneers_filename="p.xlsx",
        )


def test_session_usable_after_constraint_failure(session: Session) -> None:
    suppliers = SupplierRepository(session)
    first = suppliers.create(name="Keep Me", parser_type="pdf")
    session.commit()

    with pytest.raises(IntegrityError):
        suppliers.create(name="Keep Me", parser_type="other")

    # After rollback inside the repository, the session accepts new work.
    second = suppliers.create(name="Another", parser_type="pdf")
    session.commit()

    assert suppliers.get_by_id(first.id) is not None
    assert suppliers.get_by_name("Another") is not None
    assert second.name == "Another"


def test_session_usable_after_statement_error(session: Session) -> None:
    """StatementError on flush (not only IntegrityError) must roll back cleanly."""
    supplier = SupplierRow(name="Stmt Supplier", parser_type="pdf")
    session.add(supplier)
    session.flush()
    job = JobRow(
        supplier_id=supplier.id,
        source_filename="s.xlsx",
        pioneers_filename="p.xlsx",
        status="PENDING",
    )
    session.add(job)
    session.flush()
    session.commit()

    # Bypass repository validation: TypeDecorator rejects NaN at bind → StatementError.
    session.add(
        JobItemRow(
            job_id=job.id,
            status="MATCHED",
            old_price=Decimal("NaN"),
        )
    )
    with pytest.raises((StatementError, ValueError)):
        flush_or_rollback(session)

    # Session must accept new work after rollback.
    created = SupplierRepository(session).create(name="After Stmt", parser_type="pdf")
    assert created.name == "After Stmt"
