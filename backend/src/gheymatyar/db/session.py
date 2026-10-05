"""SQLAlchemy engine and session factory for SQLite.

Scaffold only: no models or business logic yet. Production will use a
local SQLite file; tests can override the URL later.
"""

from collections.abc import Generator
from functools import lru_cache

from sqlalchemy import create_engine, Engine
from sqlalchemy.orm import sessionmaker, Session

DEFAULT_DATABASE_URL = "sqlite:///./gheymatyar.db"


@lru_cache
def get_engine(url: str = DEFAULT_DATABASE_URL) -> Engine:
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    return create_engine(url, connect_args=connect_args)


def get_session_factory(url: str = DEFAULT_DATABASE_URL) -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(url), autoflush=False, autocommit=False)


def get_db(url: str = DEFAULT_DATABASE_URL) -> Generator[Session, None, None]:
    """FastAPI-style dependency that yields a DB session."""
    SessionLocal = get_session_factory(url)
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
