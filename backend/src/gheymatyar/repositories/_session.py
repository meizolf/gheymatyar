"""Shared session helpers for repositories."""

from __future__ import annotations

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session


def commit_or_raise(session: Session) -> None:
    """Commit now. On failure, roll back and re-raise.

    Call this before treating a mutation as successful and before copying the
    new state into memory. The request dependency also commits after the
    response is built; a failure at that later point cannot undo a success
    body that was already returned.
    """
    try:
        session.commit()
    except SQLAlchemyError:
        session.rollback()
        raise


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
