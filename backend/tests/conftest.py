"""Shared fixtures for backend tests.

Every persistence test gets an isolated temporary SQLite file — never the
developer's real application database.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from gheymatyar.db import Database
from gheymatyar.main import create_app
from gheymatyar.services.session_store import SessionStore

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES = REPO_ROOT / "fixtures"
PIONEERS_SAMPLE = FIXTURES / "pioneers" / "pioneers_sample.xlsx"
PIONEERS_LITE = FIXTURES / "pioneers" / "pioneers_lite_sample.xlsx"
PIONEERS_AZIN = FIXTURES / "pioneers" / "pioneers_azin_subset.xlsx"
AZIN_PDF = FIXTURES / "suppliers" / "458_124550609784457.pdf"


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


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    """API client bound to an isolated temp database and session store."""
    db_path = tmp_path / "api.db"
    app = create_app(database_url=f"sqlite:///{db_path}", mount_spa=False)
    # Isolate in-memory sessions per test.
    store = SessionStore()
    app.state.sessions = store
    from gheymatyar.services.processing import ProcessingService

    app.state.processing = ProcessingService(store)
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def azin_pdf() -> Path:
    if not AZIN_PDF.is_file():
        pytest.skip(f"missing Azin PDF fixture: {AZIN_PDF}")
    return AZIN_PDF


@pytest.fixture
def pioneers_azin_excel() -> Path:
    if not PIONEERS_AZIN.is_file():
        pytest.skip(f"missing Pioneers azin subset: {PIONEERS_AZIN}")
    return PIONEERS_AZIN


@pytest.fixture
def pioneers_lite_excel() -> Path:
    if not PIONEERS_LITE.is_file():
        pytest.skip(f"missing Pioneers lite fixture: {PIONEERS_LITE}")
    return PIONEERS_LITE
