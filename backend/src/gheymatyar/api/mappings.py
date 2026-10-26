"""Saved name-mapping CRUD endpoints (supplier-scoped)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from gheymatyar.api.deps import get_db_session
from gheymatyar.api.schemas import (
    MappingResponse,
    MappingsListResponse,
    MappingUpdateRequest,
)
from gheymatyar.domain.enums import MappingType
from gheymatyar.repositories._session import commit_or_raise
from gheymatyar.repositories.exceptions import MappingNotFoundError
from gheymatyar.repositories.mapping_repository import UNSET, MappingRepository
from gheymatyar.repositories.records import ProductMappingRecord, SupplierRecord
from gheymatyar.repositories.product_decision_repository import ProductDecisionRepository
from gheymatyar.repositories.supplier_repository import SupplierRepository
from gheymatyar.services.mapping_uniqueness import (
    MAPPING_WRITE_LOCK,
    DuplicateMappingTargetError,
    duplicate_saved_targets,
    pioneers_target,
    saved_holders,
)
from gheymatyar.services.name_normalization import normalize_product_name
from gheymatyar.suppliers.errors import UnsupportedSupplierError
from gheymatyar.suppliers.registry import get_default_registry

router = APIRouter(tags=["mappings"])


def _resolve_supplier_row(db: Session, supplier_key: str) -> SupplierRecord:
    """Resolve DB supplier row by registry key (parser_type)."""
    try:
        processor = get_default_registry().get(supplier_key)
    except UnsupportedSupplierError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    repo = SupplierRepository(db)
    for row in repo.list_all():
        if row.parser_type == supplier_key:
            return row
    by_name = repo.get_by_name(processor.display_name)
    if by_name is not None:
        return by_name
    return repo.create(name=processor.display_name, parser_type=supplier_key)


def _to_response(
    record: ProductMappingRecord,
    supplier_key: str,
    conflicts_with: list[str] | None = None,
) -> MappingResponse:
    return MappingResponse(
        id=record.id,
        supplier_key=supplier_key,
        supplier_name_raw=record.supplier_name_raw,
        supplier_name_normalized=record.supplier_name_normalized,
        pioneers_name_raw=record.pioneers_name_raw,
        pioneers_name_normalized=record.pioneers_name_normalized,
        pioneers_code=record.pioneers_code,
        supplier_code=record.supplier_code,
        unit_normalized=record.unit_normalized,
        legacy_unscoped=record.legacy_unscoped,
        mapping_type=record.mapping_type,
        created_at=record.created_at.isoformat(),
        updated_at=record.updated_at.isoformat(),
        conflicts_with=conflicts_with or [],
    )


@router.get(
    "/suppliers/{supplier_key}/mappings",
    response_model=MappingsListResponse,
)
def list_mappings(
    supplier_key: str,
    db: Session = Depends(get_db_session),
) -> MappingsListResponse:
    supplier = _resolve_supplier_row(db, supplier_key)
    rows = MappingRepository(db).list_for_supplier(supplier.id)
    ignored = ProductDecisionRepository(db).ignored_identity_keys(supplier.id)
    duplicates = duplicate_saved_targets(rows, ignored)
    return MappingsListResponse(
        supplier_key=supplier_key,
        mappings=[
            _to_response(
                r,
                supplier_key,
                [other.supplier_name_raw for other in duplicates.get(r.id, [])],
            )
            for r in rows
        ],
    )


@router.put(
    "/suppliers/{supplier_key}/mappings/{mapping_id}",
    response_model=MappingResponse,
)
def update_mapping(
    supplier_key: str,
    mapping_id: int,
    body: MappingUpdateRequest,
    db: Session = Depends(get_db_session),
) -> MappingResponse:
    supplier = _resolve_supplier_row(db, supplier_key)
    repo = MappingRepository(db)
    existing = repo.get_by_id(mapping_id)
    if existing is None or existing.supplier_id != supplier.id:
        raise HTTPException(status_code=404, detail="mapping not found")
    pioneers_code = (
        body.pioneers_code if "pioneers_code" in body.model_fields_set else UNSET
    )
    target_code = existing.pioneers_code if pioneers_code is UNSET else pioneers_code
    try:
        # Check and save under one lock so two edits cannot claim one product.
        with MAPPING_WRITE_LOCK:
            holders = saved_holders(
                repo.list_for_supplier(supplier.id),
                target=pioneers_target(target_code, body.pioneers_name_raw),
                ignored_identities=ProductDecisionRepository(db).ignored_identity_keys(
                    supplier.id
                ),
                exclude_mapping_id=existing.id,
            )
            if holders:
                raise DuplicateMappingTargetError(
                    pioneers_code=(target_code or "").strip() or None,
                    pioneers_name=body.pioneers_name_raw,
                    holders=holders,
                )
            updated = repo.update(
                supplier_id=supplier.id,
                identity_key=existing.identity_key,
                pioneers_name_raw=body.pioneers_name_raw,
                pioneers_code=pioneers_code,
                pioneers_name_normalized=normalize_product_name(body.pioneers_name_raw),
                mapping_type=MappingType.MANUAL,
            )
            commit_or_raise(db)
    except DuplicateMappingTargetError as exc:
        raise HTTPException(status_code=409, detail=exc.to_detail()) from exc
    except MappingNotFoundError as exc:
        raise HTTPException(status_code=404, detail="mapping not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=500, detail="could not save the decision") from exc
    return _to_response(updated, supplier_key)


@router.delete(
    "/suppliers/{supplier_key}/mappings/{mapping_id}",
    status_code=204,
)
def delete_mapping(
    supplier_key: str,
    mapping_id: int,
    db: Session = Depends(get_db_session),
) -> None:
    supplier = _resolve_supplier_row(db, supplier_key)
    repo = MappingRepository(db)
    existing = repo.get_by_id(mapping_id)
    if existing is None or existing.supplier_id != supplier.id:
        raise HTTPException(status_code=404, detail="mapping not found")
    try:
        repo.delete(mapping_id)
        commit_or_raise(db)
    except MappingNotFoundError as exc:
        raise HTTPException(status_code=404, detail="mapping not found") from exc
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=500, detail="could not save the decision") from exc
