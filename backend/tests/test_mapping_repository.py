"""MappingRepository tests."""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from gheymatyar.domain import MappingType
from gheymatyar.repositories import (
    MappingConflictError,
    MappingNotFoundError,
    MappingRepository,
    SupplierRepository,
)


def _supplier(session: Session, name: str = "Supplier A") -> int:
    return SupplierRepository(session).create(name=name, parser_type="pdf").id


def test_save_and_retrieve_mapping(session: Session) -> None:
    supplier_id = _supplier(session)
    repo = MappingRepository(session)

    created = repo.create(
        supplier_id=supplier_id,
        supplier_code="ABC",
        pioneers_code="100",
        mapping_type=MappingType.AUTO_CODE,
    )
    assert created.supplier_code == "ABC"
    assert created.pioneers_code == "100"
    assert created.mapping_type == MappingType.AUTO_CODE.value

    fetched = repo.get_by_supplier_code(supplier_id, "ABC")
    assert fetched is not None
    assert fetched.id == created.id


def test_list_mappings_for_supplier(session: Session) -> None:
    supplier_id = _supplier(session)
    repo = MappingRepository(session)
    repo.create(
        supplier_id=supplier_id,
        supplier_code="A1",
        pioneers_code="P1",
        mapping_type=MappingType.MANUAL,
    )
    repo.create(
        supplier_id=supplier_id,
        supplier_code="A2",
        pioneers_code="P2",
        mapping_type=MappingType.AUTO_BARCODE,
    )

    codes = [m.supplier_code for m in repo.list_for_supplier(supplier_id)]
    assert codes == ["A1", "A2"]


def test_explicit_update_mapping(session: Session) -> None:
    supplier_id = _supplier(session)
    repo = MappingRepository(session)
    repo.create(
        supplier_id=supplier_id,
        supplier_code="ABC",
        pioneers_code="100",
        mapping_type=MappingType.AUTO_CODE,
    )

    updated = repo.update(
        supplier_id=supplier_id,
        supplier_code="ABC",
        pioneers_code="200",
        mapping_type=MappingType.MANUAL,
    )
    assert updated.pioneers_code == "200"
    assert updated.mapping_type == MappingType.MANUAL.value

    fetched = repo.get_by_supplier_code(supplier_id, "ABC")
    assert fetched is not None
    assert fetched.pioneers_code == "200"


def test_conflicting_duplicate_mapping_rejected(session: Session) -> None:
    supplier_id = _supplier(session)
    repo = MappingRepository(session)
    repo.create(
        supplier_id=supplier_id,
        supplier_code="ABC",
        pioneers_code="100",
        mapping_type=MappingType.AUTO_CODE,
    )

    with pytest.raises(MappingConflictError):
        repo.create(
            supplier_id=supplier_id,
            supplier_code="ABC",
            pioneers_code="200",
            mapping_type=MappingType.MANUAL,
        )

    # Original mapping unchanged (no silent overwrite).
    fetched = repo.get_by_supplier_code(supplier_id, "ABC")
    assert fetched is not None
    assert fetched.pioneers_code == "100"


def test_identical_duplicate_create_also_rejected(session: Session) -> None:
    supplier_id = _supplier(session)
    repo = MappingRepository(session)
    repo.create(
        supplier_id=supplier_id,
        supplier_code="ABC",
        pioneers_code="100",
        mapping_type=MappingType.AUTO_CODE,
    )

    with pytest.raises(MappingConflictError):
        repo.create(
            supplier_id=supplier_id,
            supplier_code="ABC",
            pioneers_code="100",
            mapping_type=MappingType.AUTO_CODE,
        )


def test_mappings_isolated_by_supplier(session: Session) -> None:
    a = _supplier(session, "Supplier A")
    b = _supplier(session, "Supplier B")
    repo = MappingRepository(session)

    repo.create(
        supplier_id=a,
        supplier_code="X",
        pioneers_code="100",
        mapping_type=MappingType.AUTO_CODE,
    )
    repo.create(
        supplier_id=b,
        supplier_code="X",
        pioneers_code="200",
        mapping_type=MappingType.MANUAL,
    )

    assert repo.get_by_supplier_code(a, "X") is not None
    assert repo.get_by_supplier_code(a, "X").pioneers_code == "100"  # type: ignore[union-attr]
    assert repo.get_by_supplier_code(b, "X").pioneers_code == "200"  # type: ignore[union-attr]


def test_update_missing_mapping_raises(session: Session) -> None:
    supplier_id = _supplier(session)
    repo = MappingRepository(session)
    with pytest.raises(MappingNotFoundError):
        repo.update(
            supplier_id=supplier_id,
            supplier_code="NOPE",
            pioneers_code="1",
        )


def test_rejected_update_leaves_mapping_unchanged(session: Session) -> None:
    """Invalid mapping_type must not partially apply pioneers_code."""
    supplier_id = _supplier(session)
    repo = MappingRepository(session)
    repo.create(
        supplier_id=supplier_id,
        supplier_code="ABC",
        pioneers_code="100",
        mapping_type=MappingType.AUTO_CODE,
    )
    session.commit()

    with pytest.raises(ValueError, match="invalid mapping_type"):
        repo.update(
            supplier_id=supplier_id,
            supplier_code="ABC",
            pioneers_code="200",
            mapping_type="not-a-real-type",
        )

    fetched = repo.get_by_supplier_code(supplier_id, "ABC")
    assert fetched is not None
    assert fetched.pioneers_code == "100"
    assert fetched.mapping_type == MappingType.AUTO_CODE.value

