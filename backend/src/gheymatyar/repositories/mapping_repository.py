"""Product name-mapping persistence repository."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from gheymatyar.db.models import ProductMappingRow, utc_now
from gheymatyar.domain.enums import MappingType
from gheymatyar.repositories._session import flush_or_rollback
from gheymatyar.repositories.exceptions import MappingConflictError, MappingNotFoundError
from gheymatyar.repositories.records import ProductMappingRecord
from gheymatyar.services.name_normalization import normalize_product_name


def _mapping_type_value(mapping_type: MappingType | str) -> str:
    if isinstance(mapping_type, MappingType):
        return mapping_type.value
    text = str(mapping_type).strip()
    if not text:
        raise ValueError("mapping_type must be non-empty")
    try:
        return MappingType(text).value
    except ValueError as exc:
        raise ValueError(f"invalid mapping_type: {mapping_type!r}") from exc


def _to_record(row: ProductMappingRow) -> ProductMappingRecord:
    return ProductMappingRecord(
        id=row.id,
        supplier_id=row.supplier_id,
        supplier_name_raw=row.supplier_name_raw,
        supplier_name_normalized=row.supplier_name_normalized,
        pioneers_name_raw=row.pioneers_name_raw,
        pioneers_name_normalized=row.pioneers_name_normalized,
        pioneers_code=row.pioneers_code,
        mapping_type=row.mapping_type,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


class MappingRepository:
    """Persist supplier↔Pioneers name mappings.

    Unique on ``(supplier_id, supplier_name_normalized)``. Create never
    silently overwrites — use :meth:`upsert` or :meth:`update`.
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    def create(
        self,
        *,
        supplier_id: int,
        supplier_name_raw: str,
        pioneers_name_raw: str,
        pioneers_code: str | None = None,
        mapping_type: MappingType | str = MappingType.MANUAL,
        supplier_name_normalized: str | None = None,
        pioneers_name_normalized: str | None = None,
    ) -> ProductMappingRecord:
        supplier_raw = supplier_name_raw.strip()
        pioneers_raw = pioneers_name_raw.strip()
        if not supplier_raw:
            raise ValueError("supplier_name_raw must be non-empty")
        if not pioneers_raw:
            raise ValueError("pioneers_name_raw must be non-empty")

        supplier_norm = (
            supplier_name_normalized.strip()
            if supplier_name_normalized
            else normalize_product_name(supplier_raw)
        )
        pioneers_norm = (
            pioneers_name_normalized.strip()
            if pioneers_name_normalized
            else normalize_product_name(pioneers_raw)
        )
        code = pioneers_code.strip() if pioneers_code else None
        if code == "":
            code = None
        type_value = _mapping_type_value(mapping_type)

        existing = self.get_by_supplier_name(supplier_id, supplier_norm)
        if existing is not None:
            raise MappingConflictError(
                f"mapping already exists for supplier_id={supplier_id} "
                f"supplier_name_normalized={supplier_norm!r} "
                f"(pioneers_name={existing.pioneers_name_raw!r}); "
                "use update() or upsert() to change it explicitly"
            )

        row = ProductMappingRow(
            supplier_id=supplier_id,
            supplier_name_raw=supplier_raw,
            supplier_name_normalized=supplier_norm,
            pioneers_name_raw=pioneers_raw,
            pioneers_name_normalized=pioneers_norm,
            pioneers_code=code,
            mapping_type=type_value,
        )
        self._session.add(row)
        flush_or_rollback(self._session)
        return _to_record(row)

    def get_by_supplier_name(
        self, supplier_id: int, supplier_name_normalized: str
    ) -> ProductMappingRecord | None:
        stmt = select(ProductMappingRow).where(
            ProductMappingRow.supplier_id == supplier_id,
            ProductMappingRow.supplier_name_normalized
            == supplier_name_normalized.strip(),
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
        supplier_name_normalized: str,
        pioneers_name_raw: str,
        pioneers_code: str | None = None,
        mapping_type: MappingType | str | None = None,
        pioneers_name_normalized: str | None = None,
        supplier_name_raw: str | None = None,
    ) -> ProductMappingRecord:
        """Explicitly update an existing mapping. Does not create new rows."""
        key = supplier_name_normalized.strip()
        pioneers_raw = pioneers_name_raw.strip()
        if not key:
            raise ValueError("supplier_name_normalized must be non-empty")
        if not pioneers_raw:
            raise ValueError("pioneers_name_raw must be non-empty")

        stmt = select(ProductMappingRow).where(
            ProductMappingRow.supplier_id == supplier_id,
            ProductMappingRow.supplier_name_normalized == key,
        )
        row = self._session.scalars(stmt).first()
        if row is None:
            raise MappingNotFoundError(
                f"no mapping for supplier_id={supplier_id} "
                f"supplier_name_normalized={key!r}"
            )

        type_value: str | None = None
        if mapping_type is not None:
            type_value = _mapping_type_value(mapping_type)

        row.pioneers_name_raw = pioneers_raw
        row.pioneers_name_normalized = (
            pioneers_name_normalized.strip()
            if pioneers_name_normalized
            else normalize_product_name(pioneers_raw)
        )
        if supplier_name_raw is not None:
            cleaned = supplier_name_raw.strip()
            if cleaned:
                row.supplier_name_raw = cleaned
        if pioneers_code is not None:
            code = pioneers_code.strip()
            row.pioneers_code = code or None
        if type_value is not None:
            row.mapping_type = type_value
        row.updated_at = utc_now()
        flush_or_rollback(self._session)
        return _to_record(row)

    def upsert(
        self,
        *,
        supplier_id: int,
        supplier_name_raw: str,
        pioneers_name_raw: str,
        pioneers_code: str | None = None,
        mapping_type: MappingType | str = MappingType.MANUAL,
    ) -> ProductMappingRecord:
        """Create or replace a mapping for the supplier product name."""
        supplier_norm = normalize_product_name(supplier_name_raw)
        existing = self.get_by_supplier_name(supplier_id, supplier_norm)
        if existing is None:
            return self.create(
                supplier_id=supplier_id,
                supplier_name_raw=supplier_name_raw,
                pioneers_name_raw=pioneers_name_raw,
                pioneers_code=pioneers_code,
                mapping_type=mapping_type,
            )
        return self.update(
            supplier_id=supplier_id,
            supplier_name_normalized=supplier_norm,
            pioneers_name_raw=pioneers_name_raw,
            pioneers_code=pioneers_code,
            mapping_type=mapping_type,
            supplier_name_raw=supplier_name_raw,
        )

    def get_by_id(self, mapping_id: int) -> ProductMappingRecord | None:
        row = self._session.get(ProductMappingRow, mapping_id)
        return _to_record(row) if row is not None else None

    def delete(self, mapping_id: int) -> None:
        """Remove a mapping by primary key. Raises MappingNotFoundError if missing."""
        row = self._session.get(ProductMappingRow, mapping_id)
        if row is None:
            raise MappingNotFoundError(f"no mapping with id={mapping_id}")
        self._session.delete(row)
        flush_or_rollback(self._session)
