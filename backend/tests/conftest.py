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
TOP_PDF = FIXTURES / "suppliers" / "top_industrial.pdf"
DINA_PDF = FIXTURES / "suppliers" / "dina_polymer_1405_07_04.pdf"
NEWPIPE_PDF = FIXTURES / "suppliers" / "newpipe_1405_07_18.pdf"
ABRAHAN_PDF = FIXTURES / "suppliers" / "abrahan_pipe_1405_07_15.pdf"
PARS_PLAST_PDF = FIXTURES / "suppliers" / "pars_plast_1405_07_11.pdf"
KAVEH_PDF = FIXTURES / "suppliers" / "kaveh_gostar_1405_06.pdf"
PG234_PDF = FIXTURES / "suppliers" / "pg234_1405_07_22.pdf"
KIAN_PDF = FIXTURES / "suppliers" / "kian_hose_mehr_1405.pdf"


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


def _require_pdf(path: Path) -> Path:
    if not path.is_file():
        pytest.skip(f"missing supplier PDF fixture: {path}")
    return path


@pytest.fixture(scope="module")
def top_pdf() -> Path:
    return _require_pdf(TOP_PDF)


@pytest.fixture(scope="module")
def dina_pdf() -> Path:
    return _require_pdf(DINA_PDF)


@pytest.fixture(scope="module")
def newpipe_pdf() -> Path:
    return _require_pdf(NEWPIPE_PDF)


@pytest.fixture(scope="module")
def abrahan_pdf() -> Path:
    return _require_pdf(ABRAHAN_PDF)


@pytest.fixture(scope="module")
def pars_plast_pdf() -> Path:
    return _require_pdf(PARS_PLAST_PDF)


@pytest.fixture(scope="module")
def kaveh_pdf() -> Path:
    return _require_pdf(KAVEH_PDF)


@pytest.fixture(scope="module")
def pg234_pdf() -> Path:
    return _require_pdf(PG234_PDF)


@pytest.fixture(scope="module")
def kian_pdf() -> Path:
    return _require_pdf(KIAN_PDF)


@pytest.fixture
def pioneers_lite_excel() -> Path:
    if not PIONEERS_LITE.is_file():
        pytest.skip(f"missing Pioneers lite fixture: {PIONEERS_LITE}")
    return PIONEERS_LITE
