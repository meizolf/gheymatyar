"""Health check and local shutdown endpoints."""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request

router = APIRouter(tags=["health"])
logger = logging.getLogger(__name__)


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.post("/shutdown")
def shutdown(request: Request) -> dict[str, str]:
    """Stop the local server. Only callable from the loopback client."""
    client = request.client
    # "testclient" is Starlette TestClient's synthetic host (not a network peer).
    if client is None or client.host not in {"127.0.0.1", "::1", "testclient"}:
        raise HTTPException(status_code=403, detail="shutdown only allowed from localhost")

    server = getattr(request.app.state, "uvicorn_server", None)
    if server is None:
        raise HTTPException(
            status_code=400,
            detail="shutdown is only available when launched via python -m gheymatyar",
        )
    logger.info("Shutdown requested from UI")
    server.should_exit = True
    return {"status": "shutting_down"}
