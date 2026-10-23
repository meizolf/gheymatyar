"""Product mapping persistence repository.

Mappings are unique per supplier variant: normalized name, supplier code, and
unit. A second variant that only shares the name gets its own row.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from gheymatyar.db.models import ProductMappingRow, utc_now
from gheymatyar.domain.enums import MappingType
from gheymatyar.repositories._session import flush_or_rollback
from gheymatyar.repositories.exceptions import MappingConflictError, MappingNotFoundError
from gheymatyar.repositories.records import ProductMappingRecord
from gheymatyar.services.name_normalization import normalize_digits, normalize_product_name
from gheymatyar.services.product_identity import supplier_product_identity

# Distinguishes "argument omitted" from an explicit null that clears a column.
UNSET: Any = object()


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


def _variant_parts(
    supplier_norm: str,
    supplier_code: str | None,
    unit: str | None,
) -> tuple[str, str | None, str | None]:
    identity = supplier_product_identity(
        normalized_name=supplier_norm,
        supplier_code=supplier_code,
        unit=unit,
    )
    code = None
    if supplier_code and str(supplier_code).strip():
        code = normalize_digits(str(supplier_code).strip()) or None
    unit_norm = None
    if unit and str(unit).strip():
        normalized_unit = normalize_product_name(str(unit))
        unit_norm = normalized_unit or None
    return identity, code, unit_norm


def _assign_pioneers_code(row: ProductMappingRow, pioneers_code: Any) -> None:
    if pioneers_code is UNSET:
        return
    if pioneers_code is None:
        row.pioneers_code = None
        return
    code = str(pioneers_code).strip()
    row.pioneers_code = code or None


def _to_record(row: ProductMappingRow) -> ProductMappingRecord:
    return ProductMappingRecord(
        id=row.id,
        supplier_id=row.supplier_id,
        supplier_name_raw=row.supplier_name_raw,
        supplier_name_normalized=row.supplier_name_normalized,
        pioneers_name_raw=row.pioneers_name_raw,
        pioneers_name_normalized=row.pioneers_name_normalized,
        pioneers_code=row.pioneers_code,
        identity_key=row.identity_key,
        supplier_code=row.supplier_code,
        unit_normalized=row.unit_normalized,
        legacy_unscoped=bool(row.legacy_unscoped),
        mapping_type=row.mapping_type,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


class MappingRepository:
    """Persist supplier↔Pioneers mappings.

    Unique on ``(supplier_id, identity_key)``. Create never silently overwrites
    — use :meth:`upsert` or :meth:`update`.
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
        supplier_code: str | None = None,
        unit: str | None = None,
        legacy_unscoped: bool = False,
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
        identity, code_stored, unit_norm = _variant_parts(
            supplier_norm, supplier_code, unit
        )
        type_value = _mapping_type_value(mapping_type)
        target_code = pioneers_code.strip() if pioneers_code else None
        if target_code == "":
            target_code = None

        existing = self.get_by_identity(supplier_id, identity)
        if existing is not None:
            raise MappingConflictError(
                f"mapping already exists for supplier_id={supplier_id} "
                f"identity_key={identity!r} "
                f"(pioneers_name={existing.pioneers_name_raw!r}); "
                "use update() or upsert() to change it explicitly"
            )

        row = ProductMappingRow(
            supplier_id=supplier_id,
            identity_key=identity,
            supplier_name_raw=supplier_raw,
            supplier_name_normalized=supplier_norm,
            supplier_code=code_stored,
            unit_normalized=unit_norm,
            legacy_unscoped=legacy_unscoped,
            pioneers_name_raw=pioneers_raw,
            pioneers_name_normalized=pioneers_norm,
            pioneers_code=target_code,
            mapping_type=type_value,
        )
        self._session.add(row)
        flush_or_rollback(self._session)
        return _to_record(row)

    def get_by_supplier_name(
        self, supplier_id: int, supplier_name_normalized: str
    ) -> ProductMappingRecord | None:
        """Return one name match. Prefer :meth:`get_by_identity` for variants."""
        stmt = select(ProductMappingRow).where(
            ProductMappingRow.supplier_id == supplier_id,
            ProductMappingRow.supplier_name_normalized
            == supplier_name_normalized.strip(),
        )
        row = self._session.scalars(stmt).first()
        return _to_record(row) if row is not None else None

    def get_by_identity(
        self, supplier_id: int, identity_key: str
    ) -> ProductMappingRecord | None:
        stmt = select(ProductMappingRow).where(
            ProductMappingRow.supplier_id == supplier_id,
            ProductMappingRow.identity_key == identity_key,
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
        pioneers_name_raw: str,
        supplier_name_normalized: str | None = None,
        identity_key: str | None = None,
        pioneers_code: Any = UNSET,
        mapping_type: MappingType | str | None = None,
        pioneers_name_normalized: str | None = None,
        supplier_name_raw: str | None = None,
        legacy_unscoped: Any = UNSET,
    ) -> ProductMappingRecord:
        """Explicitly update an existing mapping. Does not create new rows.

        ``pioneers_code=None`` clears the stored code. Omitting it leaves the
        current code in place.
        """
        pioneers_raw = pioneers_name_raw.strip()
        if not pioneers_raw:
            raise ValueError("pioneers_name_raw must be non-empty")
        if not identity_key and not (supplier_name_normalized or "").strip():
            raise ValueError("identity_key or supplier_name_normalized is required")

        if identity_key:
            stmt = select(ProductMappingRow).where(
                ProductMappingRow.supplier_id == supplier_id,
                ProductMappingRow.identity_key == identity_key,
            )
            row = self._session.scalars(stmt).first()
            if row is None:
                raise MappingNotFoundError(
                    f"no mapping for supplier_id={supplier_id} "
                    f"identity_key={identity_key!r}"
                )
        else:
            key = (supplier_name_normalized or "").strip()
            stmt = select(ProductMappingRow).where(
                ProductMappingRow.supplier_id == supplier_id,
                ProductMappingRow.supplier_name_normalized == key,
            )
            rows = list(self._session.scalars(stmt))
            if not rows:
                raise MappingNotFoundError(
                    f"no mapping for supplier_id={supplier_id} "
                    f"supplier_name_normalized={key!r}"
                )
            if len(rows) != 1:
                raise ValueError(
                    "multiple mappings share that supplier name; "
                    "update the variant identity"
                )
            row = rows[0]

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
        _assign_pioneers_code(row, pioneers_code)
        if type_value is not None:
            row.mapping_type = type_value
        if legacy_unscoped is not UNSET:
            row.legacy_unscoped = bool(legacy_unscoped)
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
        supplier_name_normalized: str | None = None,
        supplier_code: str | None = None,
        unit: str | None = None,
    ) -> ProductMappingRecord:
        """Create or replace the mapping for one supplier variant.

        ``pioneers_code=None`` is an explicit clear, not "leave unchanged".
        """
        supplier_norm = (
            supplier_name_normalized.strip()
            if supplier_name_normalized
            else normalize_product_name(supplier_name_raw)
        )
        identity, _code, _unit = _variant_parts(supplier_norm, supplier_code, unit)
        existing = self.get_by_identity(supplier_id, identity)
        if existing is None:
            return self.create(
                supplier_id=supplier_id,
                supplier_name_raw=supplier_name_raw,
                pioneers_name_raw=pioneers_name_raw,
                pioneers_code=pioneers_code,
                mapping_type=mapping_type,
                supplier_name_normalized=supplier_norm,
                supplier_code=supplier_code,
                unit=unit,
                legacy_unscoped=False,
            )
        return self.update(
            supplier_id=supplier_id,
            identity_key=identity,
            pioneers_name_raw=pioneers_name_raw,
            pioneers_code=pioneers_code,
            mapping_type=mapping_type,
            supplier_name_raw=supplier_name_raw,
            legacy_unscoped=False,
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
