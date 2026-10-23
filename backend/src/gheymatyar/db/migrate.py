"""SQLite schema migrations that ``create_all`` cannot perform alone.

Migrations are intentionally non-destructive: unrecognized schemas stop with
a clear error, and existing legacy archives are never dropped. New tables
(such as ``supplier_product_decisions``) are added later by ``create_all``.

Name-based ``product_mappings`` rows are kept. When they predate variant
identity, the table is rebuilt in the same transaction and each row is marked
``legacy_unscoped`` so it is not applied to every code that shares the name.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from sqlalchemy import Engine, inspect, text

logger = logging.getLogger(__name__)

LEGACY_MAPPINGS_TABLE = "product_mappings_legacy_code"
# Rows copied aside while product_mappings is rebuilt. A crash or a failed
# copy can leave this table behind; startup must recover it before serving
# an empty active mapping table.
INTERRUPTED_MAPPING_UPGRADE = "product_mappings__pre_identity"


class MigrationError(Exception):
    """Schema cannot be migrated safely without risking data loss."""


def _unique_archive_name(existing_tables: set[str], base: str = LEGACY_MAPPINGS_TABLE) -> str:
    """Pick an unused archive table name so prior archives stay intact."""
    if base not in existing_tables:
        return base
    index = 2
    while True:
        candidate = f"{base}_{index}"
        if candidate not in existing_tables:
            return candidate
        index += 1


@contextmanager
def _migration_transaction(engine: Engine) -> Iterator[Any]:
    """Run SQLite DDL and data copy in one transaction.

    The sqlite3 driver commits before DDL unless autocommit is on and the
    transaction was started explicitly. ``engine.begin()`` therefore cannot
    roll back a failed ``product_mappings`` rebuild.
    """
    with engine.connect() as conn:
        raw = conn.connection.driver_connection
        previous_isolation = raw.isolation_level
        raw.isolation_level = None
        conn.exec_driver_sql("BEGIN IMMEDIATE")
        try:
            yield conn
        except Exception:
            conn.exec_driver_sql("ROLLBACK")
            raise
        else:
            conn.exec_driver_sql("COMMIT")
        finally:
            raw.isolation_level = previous_isolation


def migrate_schema(engine: Engine) -> list[str]:
    """Apply pending schema upgrades. Returns human-readable action notes.

    Raises:
        MigrationError: when ``product_mappings`` exists but is neither the
            current name-based schema nor the known legacy code-based schema,
            or when an interrupted upgrade cannot be reconciled without
            risking the preserved rows. The tables are left untouched.
    """
    notes: list[str] = []
    with _migration_transaction(engine) as conn:
        notes.extend(_recover_interrupted_variant_upgrade(conn))
        inspect(conn).clear_cache()
        inspector = inspect(conn)
        tables = set(inspector.get_table_names())
        if "product_mappings" not in tables:
            return notes

        columns = {col["name"] for col in inspector.get_columns("product_mappings")}
        if "supplier_name_normalized" in columns:
            if "identity_key" not in columns:
                notes.extend(_upgrade_name_mappings_to_variant_identity(conn))
            return notes

        if "supplier_code" not in columns:
            # Unknown shape — do not drop or rewrite; operator must intervene.
            raise MigrationError(
                "product_mappings exists with an unrecognized schema and cannot "
                "be migrated automatically. Columns present: "
                f"{sorted(columns)}. Rename or back up the table manually, then "
                "restart so a fresh name-based product_mappings table can be created."
            )

        # Known legacy code-based mappings: archive without destroying prior archives.
        archive_name = _unique_archive_name(tables)
        conn.execute(
            text(f"ALTER TABLE product_mappings RENAME TO {archive_name}")
        )
        notes.append(
            "renamed legacy code-based product_mappings to "
            f"{archive_name}; name mappings require reconfirmation"
        )
        if archive_name != LEGACY_MAPPINGS_TABLE:
            notes.append(
                f"preserved existing archive table {LEGACY_MAPPINGS_TABLE} "
                f"(and any numbered siblings)"
            )
        # New empty name-based table is created by subsequent create_all().
    return notes


def _table_names(conn: Any) -> set[str]:
    return set(inspect(conn).get_table_names())


def _count(conn: Any, table: str) -> int:
    if table not in {INTERRUPTED_MAPPING_UPGRADE, "product_mappings"}:
        raise MigrationError(f"unexpected mapping table {table}")
    value = conn.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar()
    return int(value or 0)


def _copy_legacy_name_rows(conn: Any, source: str) -> None:
    """Copy name-only rows into the variant schema. ``source`` is fixed."""
    if source != INTERRUPTED_MAPPING_UPGRADE:
        raise MigrationError(f"unexpected mapping source {source}")
    conn.execute(
        text(
            f"""
            INSERT INTO product_mappings (
                id, supplier_id, identity_key, supplier_name_raw,
                supplier_name_normalized, supplier_code, unit_normalized,
                legacy_unscoped, pioneers_name_raw, pioneers_name_normalized,
                pioneers_code, mapping_type, created_at, updated_at
            )
            SELECT
                id,
                supplier_id,
                supplier_name_normalized || char(31) || char(31),
                supplier_name_raw,
                supplier_name_normalized,
                NULL,
                NULL,
                1,
                pioneers_name_raw,
                pioneers_name_normalized,
                pioneers_code,
                mapping_type,
                created_at,
                updated_at
            FROM {source}
            """
        )
    )


def _recover_interrupted_variant_upgrade(conn: Any) -> list[str]:
    """Finish or refuse a rebuild that stopped after the table was renamed.

    Preserved rows in ``product_mappings__pre_identity`` are copied back before
    startup continues. An empty active table is never left as the only result
    while those rows still exist.
    """
    if INTERRUPTED_MAPPING_UPGRADE not in _table_names(conn):
        return []
    preserved = _count(conn, INTERRUPTED_MAPPING_UPGRADE)
    if "product_mappings" not in _table_names(conn):
        conn.execute(
            text(
                f"ALTER TABLE {INTERRUPTED_MAPPING_UPGRADE} "
                "RENAME TO product_mappings"
            )
        )
        return [
            "restored product_mappings from an interrupted upgrade "
            "before retrying the variant migration"
        ]

    columns = {col["name"] for col in inspect(conn).get_columns("product_mappings")}
    active = _count(conn, "product_mappings")
    if "identity_key" not in columns:
        raise MigrationError(
            "product_mappings upgrade was interrupted. The active table is not "
            "the variant schema while "
            f"{INTERRUPTED_MAPPING_UPGRADE} still holds {preserved} mapping(s). "
            "Startup will not continue with a partial mapping table."
        )
    if preserved and active == 0:
        _copy_legacy_name_rows(conn, INTERRUPTED_MAPPING_UPGRADE)
        copied = _count(conn, "product_mappings")
        if copied != preserved:
            raise MigrationError(
                "could not recover every stranded product mapping "
                f"({copied} copied of {preserved})"
            )
        conn.execute(text(f"DROP TABLE {INTERRUPTED_MAPPING_UPGRADE}"))
        return [
            "recovered stranded product_mappings from an interrupted "
            "variant-identity upgrade"
        ]
    if preserved and active:
        missing = conn.execute(
            text(
                f"""
                SELECT COUNT(*) FROM {INTERRUPTED_MAPPING_UPGRADE} AS saved
                WHERE NOT EXISTS (
                    SELECT 1 FROM product_mappings AS active
                    WHERE active.id = saved.id
                )
                """
            )
        ).scalar()
        if int(missing or 0):
            raise MigrationError(
                "product_mappings and the interrupted upgrade copy both contain "
                "rows that were not reconciled. Startup will not drop either table."
            )
        conn.execute(text(f"DROP TABLE {INTERRUPTED_MAPPING_UPGRADE}"))
        return ["removed a completed product_mappings upgrade copy"]
    conn.execute(text(f"DROP TABLE {INTERRUPTED_MAPPING_UPGRADE}"))
    return ["dropped an empty interrupted product_mappings upgrade copy"]


def _upgrade_name_mappings_to_variant_identity(conn: Any) -> list[str]:
    """Copy name-only mappings onto variant identity without dropping rows.

    Existing rows become ``legacy_unscoped``. Their identity is the normalized
    name with an empty code and unit, matching ``supplier_product_identity``.
    The unique key changes from ``(supplier_id, supplier_name_normalized)`` to
    ``(supplier_id, identity_key)``.
    """
    conn.execute(
        text(
            f"ALTER TABLE product_mappings RENAME TO {INTERRUPTED_MAPPING_UPGRADE}"
        )
    )
    conn.execute(
        text(
            """
            CREATE TABLE product_mappings (
                id INTEGER NOT NULL PRIMARY KEY,
                supplier_id INTEGER NOT NULL,
                identity_key TEXT NOT NULL,
                supplier_name_raw TEXT NOT NULL,
                supplier_name_normalized VARCHAR(512) NOT NULL,
                supplier_code VARCHAR(255),
                unit_normalized VARCHAR(255),
                legacy_unscoped BOOLEAN NOT NULL DEFAULT 0,
                pioneers_name_raw TEXT NOT NULL,
                pioneers_name_normalized VARCHAR(512) NOT NULL,
                pioneers_code VARCHAR(255),
                mapping_type VARCHAR(32) NOT NULL,
                created_at DATETIME NOT NULL,
                updated_at DATETIME NOT NULL,
                CONSTRAINT uq_product_mappings_supplier_variant
                    UNIQUE (supplier_id, identity_key),
                FOREIGN KEY(supplier_id) REFERENCES suppliers (id) ON DELETE CASCADE
            )
            """
        )
    )
    # char(31) is the identity separator. Empty code and unit keep the row
    # legacy_unscoped so it is not applied to every later variant.
    _copy_legacy_name_rows(conn, INTERRUPTED_MAPPING_UPGRADE)
    copied = _count(conn, "product_mappings")
    preserved = _count(conn, INTERRUPTED_MAPPING_UPGRADE)
    if copied != preserved:
        raise MigrationError(
            "variant migration copied "
            f"{copied} of {preserved} product mappings; refusing to drop the backup"
        )
    conn.execute(text(f"DROP TABLE {INTERRUPTED_MAPPING_UPGRADE}"))
    return [
        "preserved product_mappings and marked existing name-only rows "
        "legacy_unscoped; each code or unit must be confirmed explicitly"
    ]


def list_legacy_code_mappings(conn: Any) -> list[dict[str, Any]]:
    """Read preserved legacy code mappings (if the archive table exists)."""
    inspector = inspect(conn)
    if LEGACY_MAPPINGS_TABLE not in inspector.get_table_names():
        return []
    rows = conn.execute(
        text(
            f"SELECT id, supplier_id, supplier_code, pioneers_code, mapping_type, "
            f"created_at, updated_at FROM {LEGACY_MAPPINGS_TABLE} ORDER BY id"
        )
    ).mappings()
    return [dict(row) for row in rows]
