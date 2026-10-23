"""Persistent ignore/restore decisions, isolated per supplier and identity."""

from __future__ import annotations

from sqlalchemy.orm import Session

from gheymatyar.repositories import (
    ProductDecisionRepository,
    ProductDecisionState,
    SupplierRepository,
)
from gheymatyar.services.name_normalization import normalize_product_name


def _supplier(session: Session, name: str, parser_type: str = "azin_pipe") -> int:
    return SupplierRepository(session).create(name=name, parser_type=parser_type).id


def test_ignore_is_idempotent_and_restore_updates_the_same_row(session: Session) -> None:
    supplier_id = _supplier(session, "آذین لوله")
    repo = ProductDecisionRepository(session)
    first = repo.ignore(
        supplier_id=supplier_id,
        supplier_name_raw="اذین لوله 20",
        supplier_name_normalized=normalize_product_name("اذین لوله 20"),
        supplier_code="100",
        unit="عدد",
    )
    second = repo.ignore(
        supplier_id=supplier_id,
        supplier_name_raw="اذین لوله ۲۰",
        supplier_name_normalized=normalize_product_name("اذین لوله ۲۰"),
        supplier_code="۱۰۰",
        unit="عدد",
    )
    assert first.id == second.id
    assert repo.ignored_identity_keys(supplier_id) == {first.identity_key}

    restored = repo.restore(
        supplier_id=supplier_id,
        supplier_name_raw="اذین لوله 20",
        supplier_name_normalized=normalize_product_name("اذین لوله 20"),
        supplier_code="100",
        unit="عدد",
    )
    assert restored.id == first.id
    assert restored.decision == ProductDecisionState.ACTIVE.value
    assert repo.ignored_identity_keys(supplier_id) == set()


def test_variants_and_suppliers_do_not_share_decisions(session: Session) -> None:
    azin = _supplier(session, "آذین لوله", "azin_pipe")
    dina = _supplier(session, "دینا پلیمر", "dina_polymer")
    repo = ProductDecisionRepository(session)
    name = normalize_product_name("لوله 20")
    ignored = repo.ignore(
        supplier_id=azin,
        supplier_name_raw="لوله 20",
        supplier_name_normalized=name,
        supplier_code="A",
        unit="عدد",
    )
    other_code = repo.ignore(
        supplier_id=azin,
        supplier_name_raw="لوله 20",
        supplier_name_normalized=name,
        supplier_code="B",
        unit="عدد",
    )
    other_unit = repo.ignore(
        supplier_id=azin,
        supplier_name_raw="لوله 20",
        supplier_name_normalized=name,
        supplier_code="A",
        unit="متر",
    )
    assert len({ignored.id, other_code.id, other_unit.id}) == 3
    assert ignored.identity_key != other_code.identity_key
    assert ignored.identity_key != other_unit.identity_key

    same_on_other_supplier = repo.get(dina, ignored.identity_key)
    assert same_on_other_supplier is None
    assert repo.ignored_identity_keys(dina) == set()
    assert repo.ignored_identity_keys(azin) == {
        ignored.identity_key,
        other_code.identity_key,
        other_unit.identity_key,
    }
