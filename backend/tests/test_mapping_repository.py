"""MappingRepository tests (name-based mappings)."""

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
from gheymatyar.services.name_normalization import normalize_product_name


def _supplier(session: Session, name: str = "آذین لوله") -> int:
    return SupplierRepository(session).create(name=name, parser_type="azin_pipe").id


def test_save_and_retrieve_mapping(session: Session) -> None:
    supplier_id = _supplier(session)
    repo = MappingRepository(session)

    created = repo.create(
        supplier_id=supplier_id,
        supplier_name_raw="اذین لوله سه لایه 20",
        pioneers_name_raw="اذین لوله سه لایه 20",
        pioneers_code="16251",
        mapping_type=MappingType.MANUAL,
    )
    assert created.supplier_name_raw == "اذین لوله سه لایه 20"
    assert created.pioneers_code == "16251"
    assert created.mapping_type == MappingType.MANUAL.value
    assert created.supplier_name_normalized == normalize_product_name(
        "اذین لوله سه لایه 20"
    )

    fetched = repo.get_by_supplier_name(
        supplier_id, created.supplier_name_normalized
    )
    assert fetched is not None
    assert fetched.id == created.id


def test_list_mappings_for_supplier(session: Session) -> None:
    supplier_id = _supplier(session)
    repo = MappingRepository(session)
    repo.create(
        supplier_id=supplier_id,
        supplier_name_raw="اذین بوشن 20",
        pioneers_name_raw="اذین بوشن 20",
        mapping_type=MappingType.MANUAL,
    )
    repo.create(
        supplier_id=supplier_id,
        supplier_name_raw="اذین زانو 90 درجه 20",
        pioneers_name_raw="اذین زانو 90 درجه 20",
        mapping_type=MappingType.EXACT_NAME,
    )

    names = [m.supplier_name_raw for m in repo.list_for_supplier(supplier_id)]
    assert names == ["اذین بوشن 20", "اذین زانو 90 درجه 20"]


def test_explicit_update_mapping(session: Session) -> None:
    supplier_id = _supplier(session)
    repo = MappingRepository(session)
    created = repo.create(
        supplier_id=supplier_id,
        supplier_name_raw="اذین لوله 20",
        pioneers_name_raw="اذین لوله 20",
        pioneers_code="11307",
        mapping_type=MappingType.EXACT_NAME,
    )

    updated = repo.update(
        supplier_id=supplier_id,
        supplier_name_normalized=created.supplier_name_normalized,
        pioneers_name_raw="اذین لوله 20 PP.RCT",
        pioneers_code="16246",
        mapping_type=MappingType.MANUAL,
    )
    assert updated.pioneers_name_raw == "اذین لوله 20 PP.RCT"
    assert updated.pioneers_code == "16246"
    assert updated.mapping_type == MappingType.MANUAL.value


def test_create_conflict(session: Session) -> None:
    supplier_id = _supplier(session)
    repo = MappingRepository(session)
    repo.create(
        supplier_id=supplier_id,
        supplier_name_raw="اذین بوشن 20",
        pioneers_name_raw="اذین بوشن 20",
        mapping_type=MappingType.MANUAL,
    )
    with pytest.raises(MappingConflictError):
        repo.create(
            supplier_id=supplier_id,
            supplier_name_raw="اذین بوشن 20",
            pioneers_name_raw="other",
            mapping_type=MappingType.MANUAL,
        )


def test_update_missing(session: Session) -> None:
    supplier_id = _supplier(session)
    repo = MappingRepository(session)
    with pytest.raises(MappingNotFoundError):
        repo.update(
            supplier_id=supplier_id,
            supplier_name_normalized="missing",
            pioneers_name_raw="x",
        )


def test_upsert_creates_and_updates(session: Session) -> None:
    supplier_id = _supplier(session)
    repo = MappingRepository(session)
    first = repo.upsert(
        supplier_id=supplier_id,
        supplier_name_raw="اذین درپوش 20",
        pioneers_name_raw="اذین درپوش 20",
        pioneers_code="1",
    )
    second = repo.upsert(
        supplier_id=supplier_id,
        supplier_name_raw="اذین درپوش 20",
        pioneers_name_raw="اذین درپوش گپ 20",
        pioneers_code="2",
    )
    assert first.id == second.id
    assert second.pioneers_name_raw == "اذین درپوش گپ 20"
    assert second.pioneers_code == "2"


def test_mappings_are_supplier_specific(session: Session) -> None:
    a = _supplier(session, "Supplier A")
    b = _supplier(session, "Supplier B")
    repo = MappingRepository(session)
    repo.create(
        supplier_id=a,
        supplier_name_raw="لوله 20",
        pioneers_name_raw="اذین لوله 20",
        mapping_type=MappingType.MANUAL,
    )
    repo.create(
        supplier_id=b,
        supplier_name_raw="لوله 20",
        pioneers_name_raw="پارس پلاست لوله 20",
        mapping_type=MappingType.MANUAL,
    )
    assert len(repo.list_for_supplier(a)) == 1
    assert len(repo.list_for_supplier(b)) == 1
    assert (
        repo.list_for_supplier(a)[0].pioneers_name_raw
        != repo.list_for_supplier(b)[0].pioneers_name_raw
    )
