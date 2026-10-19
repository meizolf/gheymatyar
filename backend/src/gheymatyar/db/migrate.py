"""SQLite schema migrations that ``create_all`` cannot perform alone.

Migrations are intentionally non-destructive: unrecognized schemas stop with
a clear error, and existing legacy archives are never dropped.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import Engine, inspect, text

logger = logging.getLogger(__name__)

LEGACY_MAPPINGS_TABLE = "product_mappings_legacy_code"


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


def migrate_schema(engine: Engine) -> list[str]:
    """Apply pending schema upgrades. Returns human-readable action notes.

    Raises:
        MigrationError: when ``product_mappings`` exists but is neither the
            current name-based schema nor the known legacy code-based schema.
            The table is left untouched.
    """
    notes: list[str] = []
    with engine.begin() as conn:
        inspector = inspect(conn)
        tables = set(inspector.get_table_names())
        if "product_mappings" not in tables:
            return notes

        columns = {col["name"] for col in inspector.get_columns("product_mappings")}
        if "supplier_name_normalized" in columns:
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
