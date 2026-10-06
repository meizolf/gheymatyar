"""SQLAlchemy engine, session factory, and initialization helpers.

Importing this module does not open a database connection or create files.
Callers must construct a ``Database`` (or use the lower-level helpers)
with an explicit SQLite URL.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from gheymatyar.db.models import Base, utc_now

__all__ = [
    "Database",
    "create_engine_for_url",
    "create_session_factory",
    "init_db",
    "session_scope",
    "utc_now",
]


def _enable_sqlite_foreign_keys(dbapi_connection: Any, _connection_record: Any) -> None:
    """SQLite disables FK enforcement unless PRAGMA foreign_keys=ON is set."""
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def create_engine_for_url(url: str, *, echo: bool = False) -> Engine:
    """Create a SQLAlchemy engine for the given database URL.

    For SQLite URLs, foreign-key enforcement is enabled on every connection.
    """
    connect_args: dict[str, Any] = {}
    if url.startswith("sqlite"):
        # Needed when the same connection is used across threads (e.g. tests).
        connect_args["check_same_thread"] = False

    engine = create_engine(url, echo=echo, future=True, connect_args=connect_args)

    if url.startswith("sqlite"):
        event.listen(engine, "connect", _enable_sqlite_foreign_keys)

    return engine


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    """Return a session factory bound to ``engine``."""
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def init_db(engine: Engine) -> None:
    """Create all ORM-mapped tables if they do not already exist."""
    Base.metadata.create_all(bind=engine)


@contextmanager
def session_scope(session_factory: sessionmaker[Session]) -> Iterator[Session]:
    """Provide a transactional scope around a series of operations.

    Commits on success; rolls back and re-raises on any exception so the
    session is left in a usable state for the caller to discard or continue
    after obtaining a fresh session from the factory.
    """
    session = session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


class Database:
    """Owns an engine and session factory for a configured SQLite path/URL.

    Example::

        db = Database("sqlite:////tmp/gheymatyar-dev.db")
        db.create_tables()
        with db.session() as session:
            ...
    """

    def __init__(self, url: str, *, echo: bool = False) -> None:
        self.url = url
        self.engine = create_engine_for_url(url, echo=echo)
        self.session_factory = create_session_factory(self.engine)

    def create_tables(self) -> None:
        """Initialize schema (idempotent create_all)."""
        init_db(self.engine)

    @contextmanager
    def session(self) -> Iterator[Session]:
        """Yield a session that commits on success and rolls back on error."""
        with session_scope(self.session_factory) as session:
            yield session
