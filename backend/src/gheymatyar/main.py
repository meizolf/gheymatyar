"""FastAPI application factory and root app instance."""

from fastapi import FastAPI

from gheymatyar.api import api_router


def create_app() -> FastAPI:
    app = FastAPI(
        title="Pioneers Price Updater",
        description="GheymatYar backend API",
        version="0.1.0",
    )
    app.include_router(api_router, prefix="/api")
    return app


app = create_app()
