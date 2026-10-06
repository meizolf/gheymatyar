"""Shared session helpers for repositories."""

from __future__ import annotations

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session


def flush_or_rollback(session: Session) -> None:
    """Flush pending changes; on any SQLAlchemy failure, roll back and re-raise.

    Covers ``IntegrityError``, ``StatementError`` (e.g. bind/coercion failures),
    and other ``SQLAlchemyError`` subclasses so the session is usable again.
    Database errors are not swallowed.
    """
    try:
        session.flush()
    except SQLAlchemyError:
        session.rollback()
        raise
