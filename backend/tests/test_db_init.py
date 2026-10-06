"""Tests for SQLite initialization and isolation."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import inspect

from gheymatyar.db import Database
from gheymatyar.db.models import Base


EXPECTED_TABLES = {
    "suppliers",
    "product_mappings",
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
