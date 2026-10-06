"""JobRepository tests."""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy.orm import Session

from gheymatyar.db.models import JobStatus
from gheymatyar.repositories import JobRepository, SupplierRepository


def _supplier(session: Session) -> int:
    return SupplierRepository(session).create(name="Job Supplier", parser_type="pdf").id


def test_create_and_get_job(session: Session) -> None:
    supplier_id = _supplier(session)
    repo = JobRepository(session)

    job = repo.create(
        supplier_id=supplier_id,
        source_filename="supplier.xlsx",
        pioneers_filename="pioneers.xlsx",
    )
    assert job.status == JobStatus.PENDING.value
    assert job.matched_count == 0
    assert job.unmatched_count == 0
    assert job.warning_count == 0

    fetched = repo.get_by_id(job.id)
    assert fetched is not None
    assert fetched.source_filename == "supplier.xlsx"


def test_update_status_and_counts(session: Session) -> None:
    supplier_id = _supplier(session)
    repo = JobRepository(session)
    job = repo.create(
        supplier_id=supplier_id,
        source_filename="s.xlsx",
        pioneers_filename="p.xlsx",
    )

    updated = repo.update_summary(
        job.id,
        status=JobStatus.COMPLETED,
        matched_count=10,
        unmatched_count=2,
        warning_count=1,
    )
    assert updated.status == JobStatus.COMPLETED.value
    assert updated.matched_count == 10
    assert updated.unmatched_count == 2
    assert updated.warning_count == 1


def test_add_and_list_job_items(session: Session) -> None:
    supplier_id = _supplier(session)
    repo = JobRepository(session)
    job = repo.create(
        supplier_id=supplier_id,
        source_filename="s.xlsx",
        pioneers_filename="p.xlsx",
    )

    item = repo.add_item(
        job_id=job.id,
        supplier_code="S-1",
        pioneers_code="P-1",
        old_price=Decimal("1000.50"),
        new_price=Decimal("1100.75"),
        percentage_change=Decimal("10.024975"),
        status="MATCHED",
        warning=None,
    )
    assert item.job_id == job.id

    items = repo.list_items(job.id)
    assert len(items) == 1
    assert items[0].supplier_code == "S-1"
    assert items[0].old_price == Decimal("1000.50")


def test_nullable_unmatched_fields(session: Session) -> None:
    supplier_id = _supplier(session)
    repo = JobRepository(session)
    job = repo.create(
        supplier_id=supplier_id,
        source_filename="s.xlsx",
        pioneers_filename="p.xlsx",
    )

    item = repo.add_item(
        job_id=job.id,
        supplier_code=None,
        pioneers_code=None,
        old_price=None,
        new_price=None,
        percentage_change=None,
        status="UNMATCHED",
        warning="no code on supplier row",
    )
    assert item.supplier_code is None
    assert item.pioneers_code is None
    assert item.old_price is None
    assert item.warning == "no code on supplier row"
