"""Job and job-item persistence repository."""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from gheymatyar.db.models import JobItemRow, JobRow, JobStatus
from gheymatyar.repositories._session import flush_or_rollback
from gheymatyar.repositories.records import JobItemRecord, JobRecord


def _status_value(status: JobStatus | str) -> str:
    if isinstance(status, JobStatus):
        return status.value
    text = str(status).strip()
    if not text:
        raise ValueError("status must be non-empty")
    try:
        return JobStatus(text).value
    except ValueError as exc:
        raise ValueError(f"invalid job status: {status!r}") from exc


def _ensure_decimal(value: Decimal | None, field_name: str) -> Decimal | None:
    """Accept finite Decimal (or None); reject float and non-finite values."""
    if value is None:
        return None
    if isinstance(value, float):
        raise TypeError(f"{field_name} must be Decimal, not float")
    if not isinstance(value, Decimal):
        amount = Decimal(str(value))
    else:
        amount = value
    if not amount.is_finite():
        raise ValueError(
            f"{field_name} must be a finite Decimal (got {amount!r})"
        )
    return amount


def _job_to_record(row: JobRow) -> JobRecord:
    return JobRecord(
        id=row.id,
        supplier_id=row.supplier_id,
        created_at=row.created_at,
        source_filename=row.source_filename,
        pioneers_filename=row.pioneers_filename,
        matched_count=row.matched_count,
        unmatched_count=row.unmatched_count,
        warning_count=row.warning_count,
        status=row.status,
    )


def _item_to_record(row: JobItemRow) -> JobItemRecord:
    return JobItemRecord(
        id=row.id,
        job_id=row.job_id,
        supplier_code=row.supplier_code,
        pioneers_code=row.pioneers_code,
        old_price=row.old_price,
        new_price=row.new_price,
        percentage_change=row.percentage_change,
        status=row.status,
        warning=row.warning,
    )


class JobRepository:
    """Persist processing jobs and their item history (no workflow logic)."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def create(
        self,
        *,
        supplier_id: int,
        source_filename: str,
        pioneers_filename: str,
        status: JobStatus | str = JobStatus.PENDING,
        matched_count: int = 0,
        unmatched_count: int = 0,
        warning_count: int = 0,
    ) -> JobRecord:
        row = JobRow(
            supplier_id=supplier_id,
            source_filename=source_filename,
            pioneers_filename=pioneers_filename,
            status=_status_value(status),
            matched_count=matched_count,
            unmatched_count=unmatched_count,
            warning_count=warning_count,
        )
        self._session.add(row)
        flush_or_rollback(self._session)
        return _job_to_record(row)

    def get_by_id(self, job_id: int) -> JobRecord | None:
        row = self._session.get(JobRow, job_id)
        return _job_to_record(row) if row is not None else None

    def update_summary(
        self,
        job_id: int,
        *,
        status: JobStatus | str | None = None,
        matched_count: int | None = None,
        unmatched_count: int | None = None,
        warning_count: int | None = None,
    ) -> JobRecord:
        row = self._session.get(JobRow, job_id)
        if row is None:
            raise LookupError(f"job id={job_id} not found")

        if status is not None:
            row.status = _status_value(status)
        if matched_count is not None:
            row.matched_count = matched_count
        if unmatched_count is not None:
            row.unmatched_count = unmatched_count
        if warning_count is not None:
            row.warning_count = warning_count

        flush_or_rollback(self._session)
        return _job_to_record(row)

    def add_item(
        self,
        *,
        job_id: int,
        status: str,
        supplier_code: str | None = None,
        pioneers_code: str | None = None,
        old_price: Decimal | None = None,
        new_price: Decimal | None = None,
        percentage_change: Decimal | None = None,
        warning: str | None = None,
    ) -> JobItemRecord:
        cleaned_status = status.strip()
        if not cleaned_status:
            raise ValueError("job item status must be non-empty")

        row = JobItemRow(
            job_id=job_id,
            supplier_code=supplier_code,
            pioneers_code=pioneers_code,
            old_price=_ensure_decimal(old_price, "old_price"),
            new_price=_ensure_decimal(new_price, "new_price"),
            percentage_change=_ensure_decimal(percentage_change, "percentage_change"),
            status=cleaned_status,
            warning=warning,
        )
        self._session.add(row)
        flush_or_rollback(self._session)
        return _item_to_record(row)

    def list_items(self, job_id: int) -> list[JobItemRecord]:
        stmt = (
            select(JobItemRow)
            .where(JobItemRow.job_id == job_id)
            .order_by(JobItemRow.id)
        )
        return [_item_to_record(row) for row in self._session.scalars(stmt)]
