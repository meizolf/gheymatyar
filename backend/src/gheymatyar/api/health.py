"""Health check and local shutdown endpoints."""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request

from gheymatyar.local_security import health_payload, require_local_control

router = APIRouter(tags=["health"])
logger = logging.getLogger(__name__)


@router.get("/health")
def health(request: Request) -> dict[str, str]:
    return health_payload(request.app.state)


@router.post("/shutdown")
def shutdown(request: Request) -> dict[str, str]:
    """Stop the local server. Localhost + control token required."""
    require_local_control(request)

    server = getattr(request.app.state, "uvicorn_server", None)
    if server is None:
        raise HTTPException(
            status_code=400,
            detail=(
                "shutdown is only available when launched via GheymatYar.exe "
                "or python -m gheymatyar"
            ),
        )
    logger.info("Shutdown requested from UI")
    server.should_exit = True
    return {"status": "shutting_down"}
