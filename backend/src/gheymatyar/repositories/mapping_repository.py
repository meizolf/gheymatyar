"""Product mapping persistence repository."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from gheymatyar.db.models import ProductMappingRow, utc_now
from gheymatyar.domain.enums import MappingType
from gheymatyar.repositories._session import flush_or_rollback
from gheymatyar.repositories.exceptions import MappingConflictError, MappingNotFoundError
from gheymatyar.repositories.records import ProductMappingRecord


def _mapping_type_value(mapping_type: MappingType | str) -> str:
    if isinstance(mapping_type, MappingType):
        return mapping_type.value
    text = str(mapping_type).strip()
    if not text:
        raise ValueError("mapping_type must be non-empty")
    # Accept domain enum values; reject unknown labels early.
    try:
        return MappingType(text).value
    except ValueError as exc:
        raise ValueError(f"invalid mapping_type: {mapping_type!r}") from exc


def _to_record(row: ProductMappingRow) -> ProductMappingRecord:
    return ProductMappingRecord(
        id=row.id,
        supplier_id=row.supplier_id,
        supplier_code=row.supplier_code,
        pioneers_code=row.pioneers_code,
        mapping_type=row.mapping_type,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


class MappingRepository:
    """Persist supplier↔Pioneers code mappings.

    Create never silently overwrites. Conflicting ``(supplier_id, supplier_code)``
    rows must be changed via :meth:`update`.
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    def create(
        self,
        *,
        supplier_id: int,
        supplier_code: str,
        pioneers_code: str,
        mapping_type: MappingType | str,
    ) -> ProductMappingRecord:
        code = supplier_code.strip()
        pioneers = pioneers_code.strip()
        if not code:
            raise ValueError("supplier_code must be non-empty")
        if not pioneers:
            raise ValueError("pioneers_code must be non-empty")
        type_value = _mapping_type_value(mapping_type)

        existing = self.get_by_supplier_code(supplier_id, code)
        if existing is not None:
            raise MappingConflictError(
                f"mapping already exists for supplier_id={supplier_id} "
                f"supplier_code={code!r} (pioneers_code={existing.pioneers_code!r}); "
                "use update() to change it explicitly"
            )

        row = ProductMappingRow(
            supplier_id=supplier_id,
            supplier_code=code,
            pioneers_code=pioneers,
            mapping_type=type_value,
        )
        self._session.add(row)
        # IntegrityError (e.g. FK violation or unique race) is rolled back and
        # re-raised by flush_or_rollback — not converted to MappingConflictError.
        flush_or_rollback(self._session)
        return _to_record(row)

    def get_by_supplier_code(
        self, supplier_id: int, supplier_code: str
    ) -> ProductMappingRecord | None:
        stmt = select(ProductMappingRow).where(
            ProductMappingRow.supplier_id == supplier_id,
            ProductMappingRow.supplier_code == supplier_code.strip(),
        )
        row = self._session.scalars(stmt).first()
        return _to_record(row) if row is not None else None

    def list_for_supplier(self, supplier_id: int) -> list[ProductMappingRecord]:
        stmt = (
            select(ProductMappingRow)
            .where(ProductMappingRow.supplier_id == supplier_id)
            .order_by(ProductMappingRow.id)
        )
        return [_to_record(row) for row in self._session.scalars(stmt)]

    def update(
        self,
        *,
        supplier_id: int,
        supplier_code: str,
        pioneers_code: str,
        mapping_type: MappingType | str | None = None,
    ) -> ProductMappingRecord:
        """Explicitly update an existing mapping. Does not create new rows."""
        code = supplier_code.strip()
        pioneers = pioneers_code.strip()
        if not code:
            raise ValueError("supplier_code must be non-empty")
        if not pioneers:
            raise ValueError("pioneers_code must be non-empty")

        stmt = select(ProductMappingRow).where(
            ProductMappingRow.supplier_id == supplier_id,
            ProductMappingRow.supplier_code == code,
        )
        row = self._session.scalars(stmt).first()
        if row is None:
            raise MappingNotFoundError(
                f"no mapping for supplier_id={supplier_id} supplier_code={code!r}"
            )

        # Validate optional mapping_type *before* mutating any ORM fields so a
        # rejected update cannot leave a dirty pioneers_code on the row.
        type_value: str | None = None
        if mapping_type is not None:
            type_value = _mapping_type_value(mapping_type)

        row.pioneers_code = pioneers
        if type_value is not None:
            row.mapping_type = type_value
        row.updated_at = utc_now()
        flush_or_rollback(self._session)
        return _to_record(row)
