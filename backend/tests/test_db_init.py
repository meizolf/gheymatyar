"""Tests for SQLite initialization and isolation."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import inspect

from gheymatyar.db import Database
from gheymatyar.db.models import Base


EXPECTED_TABLES = {
    "suppliers",
    "product_mappings",
    "supplier_product_decisions",
    "jobs",
    "job_items",
    "settings",
}


def test_init_creates_all_tables(db: Database) -> None:
    inspector = inspect(db.engine)
    assert EXPECTED_TABLES.issubset(set(inspector.get_table_names()))


def test_database_is_isolated_to_temp_path(tmp_path: Path) -> None:
    path = tmp_path / "isolated.db"
    assert not path.exists()

    database = Database(f"sqlite:///{path}")
    database.create_tables()
    assert path.exists()

    # A second database does not share tables/data with the first.
    other = tmp_path / "other.db"
    other_db = Database(f"sqlite:///{other}")
    other_db.create_tables()

    with database.session() as session:
        from gheymatyar.repositories import SupplierRepository

        SupplierRepository(session).create(name="Only In First", parser_type="pdf")

    with other_db.session() as session:
        from gheymatyar.repositories import SupplierRepository

        assert SupplierRepository(session).list_all() == []

    database.engine.dispose()
    other_db.engine.dispose()


def test_importing_db_module_does_not_create_files(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    # Re-importing / constructing helpers must not create a default DB beside CWD.
    from gheymatyar.db import create_engine_for_url  # noqa: F401

    assert list(tmp_path.iterdir()) == []


def test_metadata_bound_to_declarative_base() -> None:
    assert "suppliers" in Base.metadata.tables
    assert "supplier_product_decisions" in Base.metadata.tables


def test_existing_name_mappings_survive_decision_table(tmp_path: Path) -> None:
    """Adding supplier_product_decisions must not rewrite product_mappings."""
    from sqlalchemy import inspect, text

    from gheymatyar.db.database import init_db
    from gheymatyar.domain import MappingType
    from gheymatyar.repositories import MappingRepository, SupplierRepository

    database = Database(f"sqlite:///{tmp_path / 'legacy.db'}")
    database.create_tables()
    with database.session() as session:
        supplier_id = SupplierRepository(session).create(
            name="آذین لوله", parser_type="azin_pipe"
        ).id
        created = MappingRepository(session).create(
            supplier_id=supplier_id,
            supplier_name_raw="اذین لوله 20",
            pioneers_name_raw="اذین لوله 20",
            pioneers_code="11307",
            mapping_type=MappingType.MANUAL,
        )
        mapping_id = created.id

    with database.engine.begin() as conn:
        conn.execute(text("DROP TABLE supplier_product_decisions"))

    init_db(database.engine)
    tables = set(inspect(database.engine).get_table_names())
    assert "supplier_product_decisions" in tables
    assert "product_mappings" in tables

    with database.session() as session:
        loaded = MappingRepository(session).get_by_id(mapping_id)
        assert loaded is not None
        assert loaded.pioneers_name_raw == "اذین لوله 20"
        assert loaded.pioneers_code == "11307"
        assert loaded.mapping_type == MappingType.MANUAL.value
    database.engine.dispose()


def test_obsolete_sale_settings_are_removed_without_resetting_user_data(
    tmp_path: Path,
) -> None:
    from gheymatyar.db.database import init_db
    from gheymatyar.domain import MappingType
    from gheymatyar.repositories import (
        MappingRepository,
        ProductDecisionRepository,
        SettingsRepository,
        SupplierRepository,
    )

    database = Database(f"sqlite:///{tmp_path / 'kept.db'}")
    database.create_tables()
    with database.session() as session:
        supplier_id = SupplierRepository(session).create(
            name="کیان", parser_type="kian"
        ).id
        mapping = MappingRepository(session).create(
            supplier_id=supplier_id,
            supplier_name_raw="شیلنگ کیان",
            pioneers_name_raw="شیلنگ کیان",
            pioneers_code="416",
            mapping_type=MappingType.MANUAL,
        )
        ProductDecisionRepository(session).ignore(
            supplier_id=supplier_id,
            supplier_name_raw="حذف‌شده",
            supplier_name_normalized="حذف شده",
            supplier_code="999",
            unit="عدد",
        )
        SettingsRepository(session).set("suspicious_percent_threshold", "18")
        SettingsRepository(session).set("pioneers_sale_currency", "rial")
        SettingsRepository(session).set("pioneers_sale_basis", "meter")
        mapping_id = mapping.id

    init_db(database.engine)
    init_db(database.engine)

    with database.session() as session:
        settings = SettingsRepository(session)
        assert settings.get("pioneers_sale_currency") is None
        assert settings.get("pioneers_sale_basis") is None
        assert settings.get("suspicious_percent_threshold").value == "18"
        loaded = MappingRepository(session).get_by_id(mapping_id)
        assert loaded.pioneers_code == "416"
        assert loaded.pioneers_name_raw == "شیلنگ کیان"
        ignored = ProductDecisionRepository(session).list_for_supplier(supplier_id)
        assert len(ignored) == 1
        assert ignored[0].decision == "IGNORED"
        assert ignored[0].supplier_code == "999"
    database.engine.dispose()

    copied = tmp_path / "copied.db"
    copied.write_bytes((tmp_path / "kept.db").read_bytes())
    restarted = Database(f"sqlite:///{copied}")
    init_db(restarted.engine)
    with restarted.session() as session:
        settings = SettingsRepository(session)
        assert settings.get("pioneers_sale_currency") is None
        assert settings.get("pioneers_sale_basis") is None
        assert settings.get("suspicious_percent_threshold").value == "18"
        loaded = MappingRepository(session).get_by_id(mapping_id)
        assert loaded is not None
        assert loaded.pioneers_code == "416"
        ignored = ProductDecisionRepository(session).list_for_supplier(supplier_id)
        assert len(ignored) == 1
        assert ignored[0].supplier_code == "999"
    restarted.engine.dispose()
