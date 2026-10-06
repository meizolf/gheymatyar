"""Shared fixtures for persistence tests.

Every test gets an isolated temporary SQLite file — never the developer's
real application database.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from gheymatyar.db import Database


@pytest.fixture
def db(tmp_path: Path) -> Iterator[Database]:
    """Fresh SQLite database in a pytest temp directory."""
    path = tmp_path / "test.db"
    database = Database(f"sqlite:///{path}")
    database.create_tables()
    yield database
    database.engine.dispose()


@pytest.fixture
def session(db: Database) -> Iterator[Session]:
    """Open session that commits on clean exit and always closes."""
    sess = db.session_factory()
    try:
        yield sess
        sess.commit()
    except Exception:
        sess.rollback()
        raise
    finally:
        sess.close()
