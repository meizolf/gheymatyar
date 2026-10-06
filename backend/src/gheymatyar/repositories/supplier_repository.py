"""Supplier persistence repository."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from gheymatyar.db.models import SupplierRow
from gheymatyar.repositories._session import flush_or_rollback
from gheymatyar.repositories.records import SupplierRecord


def _to_record(row: SupplierRow) -> SupplierRecord:
    return SupplierRecord(
        id=row.id,
        name=row.name,
        parser_type=row.parser_type,
        created_at=row.created_at,
    )


class SupplierRepository:
    """CRUD-minimal access to the ``suppliers`` table."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def create(self, *, name: str, parser_type: str) -> SupplierRecord:
        cleaned_name = name.strip()
        cleaned_parser = parser_type.strip()
        if not cleaned_name:
            raise ValueError("supplier name must be non-empty")
        if not cleaned_parser:
            raise ValueError("parser_type must be non-empty")

        row = SupplierRow(name=cleaned_name, parser_type=cleaned_parser)
        self._session.add(row)
        flush_or_rollback(self._session)
        return _to_record(row)

    def get_by_id(self, supplier_id: int) -> SupplierRecord | None:
        row = self._session.get(SupplierRow, supplier_id)
        return _to_record(row) if row is not None else None

    def get_by_name(self, name: str) -> SupplierRecord | None:
        stmt = select(SupplierRow).where(SupplierRow.name == name.strip())
        row = self._session.scalars(stmt).first()
        return _to_record(row) if row is not None else None

    def list_all(self) -> list[SupplierRecord]:
        stmt = select(SupplierRow).order_by(SupplierRow.id)
        return [_to_record(row) for row in self._session.scalars(stmt)]
