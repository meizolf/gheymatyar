"""FastAPI application factory and root app instance."""

from __future__ import annotations

from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

from fastapi import FastAPI

from gheymatyar.api import api_router
from gheymatyar.api.deps import default_database_url
from gheymatyar.db.database import Database
from gheymatyar.services.processing import ProcessingService
from gheymatyar.services.session_store import get_session_store
from gheymatyar.static_spa import mount_frontend
from gheymatyar.suppliers.registry import get_default_registry


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    database: Database = app.state.database
    database.create_tables()
    yield
    app.state.sessions.cleanup_expired()


def create_app(*, database_url: str | None = None, mount_spa: bool = True) -> FastAPI:
    url = database_url or default_database_url()
    database = Database(url)
    sessions = get_session_store()
    processing = ProcessingService(sessions, registry=get_default_registry())

    app = FastAPI(
        title="Pioneers Price Updater",
        description="GheymatYar backend API",
        version="0.3.0",
        lifespan=lifespan,
    )
    app.state.database = database
    app.state.sessions = sessions
    app.state.processing = processing
    app.include_router(api_router, prefix="/api")
    if mount_spa:
        app.state.spa_mounted = mount_frontend(app)
    else:
        app.state.spa_mounted = False
    return app


app = create_app()
