"""SupplierRepository tests."""

from __future__ import annotations

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from gheymatyar.repositories import SupplierRepository


def test_create_and_get_by_id(session: Session) -> None:
    repo = SupplierRepository(session)
    created = repo.create(name="Acme Supplies", parser_type="excel_v1")

    assert created.id > 0
    assert created.name == "Acme Supplies"
    assert created.parser_type == "excel_v1"
    assert created.created_at.tzinfo is not None

    fetched = repo.get_by_id(created.id)
    assert fetched is not None
    assert fetched == created


def test_get_by_name(session: Session) -> None:
    repo = SupplierRepository(session)
    repo.create(name="Beta Co", parser_type="pdf_v1")

    found = repo.get_by_name("Beta Co")
    assert found is not None
    assert found.name == "Beta Co"
    assert repo.get_by_name("Missing") is None


def test_list_suppliers(session: Session) -> None:
    repo = SupplierRepository(session)
    repo.create(name="A", parser_type="p1")
    repo.create(name="B", parser_type="p2")

    names = [s.name for s in repo.list_all()]
    assert names == ["A", "B"]


def test_duplicate_supplier_name_rejected(session: Session) -> None:
    repo = SupplierRepository(session)
    repo.create(name="Dup", parser_type="p1")

    with pytest.raises(IntegrityError):
        repo.create(name="Dup", parser_type="p2")


def test_empty_name_rejected(session: Session) -> None:
    repo = SupplierRepository(session)
    with pytest.raises(ValueError, match="non-empty"):
        repo.create(name="   ", parser_type="p1")
