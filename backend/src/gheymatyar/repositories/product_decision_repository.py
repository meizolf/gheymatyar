"""Persistent ignore/restore decisions for supplier products."""

from __future__ import annotations

from enum import Enum

from sqlalchemy import select
from sqlalchemy.orm import Session

from gheymatyar.db.models import SupplierProductDecisionRow, utc_now
from gheymatyar.repositories._session import flush_or_rollback
from gheymatyar.repositories.records import SupplierProductDecisionRecord
from gheymatyar.services.name_normalization import normalize_product_name
from gheymatyar.services.product_identity import supplier_product_identity


class ProductDecisionState(str, Enum):
    """Stored user decision for one supplier product identity."""

    IGNORED = "IGNORED"
    ACTIVE = "ACTIVE"


def _clean_code(supplier_code: str | None) -> str | None:
    if supplier_code is None:
        return None
    text = str(supplier_code).strip()
    return text or None


def _unit_normalized(unit: str | None) -> str | None:
    if unit is None or not str(unit).strip():
        return None
    return normalize_product_name(str(unit))


def _to_record(row: SupplierProductDecisionRow) -> SupplierProductDecisionRecord:
    return SupplierProductDecisionRecord(
        id=row.id,
        supplier_id=row.supplier_id,
        identity_key=row.identity_key,
        supplier_name_raw=row.supplier_name_raw,
        supplier_name_normalized=row.supplier_name_normalized,
        supplier_code=row.supplier_code,
        unit_normalized=row.unit_normalized,
        decision=row.decision,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


class ProductDecisionRepository:
    """Ignore and restore supplier products without deleting source data.

    Unique on ``(supplier_id, identity_key)``. Repeating the same decision
    updates that row in place.
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    def ignore(
        self,
        *,
        supplier_id: int,
        supplier_name_raw: str,
        supplier_name_normalized: str,
        supplier_code: str | None = None,
        unit: str | None = None,
    ) -> SupplierProductDecisionRecord:
        return self._set(
            supplier_id=supplier_id,
            supplier_name_raw=supplier_name_raw,
            supplier_name_normalized=supplier_name_normalized,
            supplier_code=supplier_code,
            unit=unit,
            decision=ProductDecisionState.IGNORED,
        )

    def restore(
        self,
        *,
        supplier_id: int,
        supplier_name_raw: str,
        supplier_name_normalized: str,
        supplier_code: str | None = None,
        unit: str | None = None,
    ) -> SupplierProductDecisionRecord:
        return self._set(
            supplier_id=supplier_id,
            supplier_name_raw=supplier_name_raw,
            supplier_name_normalized=supplier_name_normalized,
            supplier_code=supplier_code,
            unit=unit,
            decision=ProductDecisionState.ACTIVE,
        )

    def ignored_identity_keys(self, supplier_id: int) -> set[str]:
        stmt = select(SupplierProductDecisionRow.identity_key).where(
            SupplierProductDecisionRow.supplier_id == supplier_id,
            SupplierProductDecisionRow.decision == ProductDecisionState.IGNORED.value,
        )
        return set(self._session.scalars(stmt))

    def get(
        self, supplier_id: int, identity_key: str
    ) -> SupplierProductDecisionRecord | None:
        stmt = select(SupplierProductDecisionRow).where(
            SupplierProductDecisionRow.supplier_id == supplier_id,
            SupplierProductDecisionRow.identity_key == identity_key,
        )
        row = self._session.scalars(stmt).first()
        return _to_record(row) if row is not None else None

    def list_for_supplier(
        self, supplier_id: int
    ) -> list[SupplierProductDecisionRecord]:
        stmt = (
            select(SupplierProductDecisionRow)
            .where(SupplierProductDecisionRow.supplier_id == supplier_id)
            .order_by(SupplierProductDecisionRow.id)
        )
        return [_to_record(row) for row in self._session.scalars(stmt)]

    def _set(
        self,
        *,
        supplier_id: int,
        supplier_name_raw: str,
        supplier_name_normalized: str,
        supplier_code: str | None,
        unit: str | None,
        decision: ProductDecisionState,
    ) -> SupplierProductDecisionRecord:
        raw_name = supplier_name_raw.strip()
        normalized = supplier_name_normalized.strip()
        if not raw_name:
            raise ValueError("supplier_name_raw must be non-empty")
        if not normalized:
            raise ValueError("supplier_name_normalized must be non-empty")
        code = _clean_code(supplier_code)
        unit_norm = _unit_normalized(unit)
        identity_key = supplier_product_identity(
            normalized_name=normalized,
            supplier_code=code,
            unit=unit,
        )
        stmt = select(SupplierProductDecisionRow).where(
            SupplierProductDecisionRow.supplier_id == supplier_id,
            SupplierProductDecisionRow.identity_key == identity_key,
        )
        row = self._session.scalars(stmt).first()
        if row is None:
            row = SupplierProductDecisionRow(
                supplier_id=supplier_id,
                identity_key=identity_key,
                supplier_name_raw=raw_name,
                supplier_name_normalized=normalized,
                supplier_code=code,
                unit_normalized=unit_norm,
                decision=decision.value,
            )
            self._session.add(row)
        else:
            row.supplier_name_raw = raw_name
            row.supplier_name_normalized = normalized
            row.supplier_code = code
            row.unit_normalized = unit_norm
            row.decision = decision.value
            row.updated_at = utc_now()
        flush_or_rollback(self._session)
        return _to_record(row)
