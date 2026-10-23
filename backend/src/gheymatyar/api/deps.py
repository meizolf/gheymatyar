"""FastAPI dependencies."""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

from fastapi import Request
from sqlalchemy.orm import Session

from gheymatyar.db.database import Database
from gheymatyar.domain.sale_policy import (
    PIONEERS_SALE_CURRENCY,
    SETTING_SALE_BASIS_KEY,
    SETTING_SALE_CURRENCY_KEY,
)
from gheymatyar.services.processing import ProcessingService
from gheymatyar.services.session_store import SessionStore

DEFAULT_SETTING_KEYS = {
    "suspicious_percent_threshold": "30",
    # Confirmed: نرخ فروش اصلی is Rial. Empty string still means "revoked".
    SETTING_SALE_CURRENCY_KEY: PIONEERS_SALE_CURRENCY,
    # Blank means the sale basis is not confirmed when the workbook has no unit.
    SETTING_SALE_BASIS_KEY: "",
}


def default_database_url() -> str:
    override = os.environ.get("GHEYMATYAR_DATABASE_URL")
    if override:
        return override
    data_dir = Path(
        os.environ.get(
            "GHEYMATYAR_DATA_DIR",
            str(Path.home() / ".gheymatyar"),
        )
    )
    data_dir.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{data_dir / 'gheymatyar.db'}"


def get_database(request: Request) -> Database:
    return request.app.state.database


def get_db_session(request: Request) -> Iterator[Session]:
    database: Database = request.app.state.database
    with database.session() as session:
        yield session


def get_sessions(request: Request) -> SessionStore:
    return request.app.state.sessions


def get_processing_service(request: Request) -> ProcessingService:
    return request.app.state.processing
