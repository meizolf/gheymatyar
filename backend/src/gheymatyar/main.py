"""FastAPI application factory and root app instance."""

from __future__ import annotations

import os
import secrets
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from gheymatyar import __version__
from gheymatyar.api import api_router
from gheymatyar.api.deps import default_database_url
from gheymatyar.db.database import Database
from gheymatyar.local_security import require_loopback_api
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


def _docs_enabled() -> bool:
    """Swagger/ReDoc pull CDN assets — disabled for offline packaged use."""
    return os.environ.get("GHEYMATYAR_ENABLE_DOCS", "").strip().lower() in {
        "1",
        "true",
        "yes",
    }


class LocalApiGuardMiddleware(BaseHTTPMiddleware):
    """Reject non-loopback Host/Origin for every ``/api`` request."""

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        if request.url.path.startswith("/api"):
            try:
                require_loopback_api(request)
            except HTTPException as exc:
                # BaseHTTPMiddleware does not translate HTTPException to a response.
                return JSONResponse(
                    status_code=exc.status_code,
                    content={"detail": exc.detail},
                )
        return await call_next(request)


def create_app(*, database_url: str | None = None, mount_spa: bool = True) -> FastAPI:
    url = database_url or default_database_url()
    database = Database(url)
    sessions = get_session_store()
    processing = ProcessingService(sessions, registry=get_default_registry())

    enable_docs = _docs_enabled()
    app = FastAPI(
        title="Pioneers Price Updater",
        description="GheymatYar backend API",
        version=__version__,
        lifespan=lifespan,
        docs_url="/docs" if enable_docs else None,
        redoc_url="/redoc" if enable_docs else None,
        openapi_url="/openapi.json" if enable_docs else None,
    )
    app.state.database = database
    app.state.sessions = sessions
    app.state.processing = processing
    app.state.app_version = __version__
    app.state.control_token = secrets.token_urlsafe(32)
    app.add_middleware(LocalApiGuardMiddleware)
    app.include_router(api_router, prefix="/api")
    if mount_spa:
        app.state.spa_mounted = mount_frontend(app)
    else:
        app.state.spa_mounted = False
    return app


app = create_app()
