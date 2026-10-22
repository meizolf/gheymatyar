"""Localhost-only request guards for the desktop app.

The UI is same-origin on ``127.0.0.1``. CORS alone does not stop a foreign
page from reading or mutating ``/api/*``. Every API request therefore requires
a loopback peer and ``Host`` header; unsafe methods also reject foreign
``Origin`` / ``Referer``. Process shutdown additionally requires the local
control token.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

from fastapi import HTTPException, Request

CONTROL_TOKEN_HEADER = "X-GheymatYar-Token"
_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})

_LOOPBACK_HOSTS = frozenset(
    {
        "127.0.0.1",
        "localhost",
        "::1",
        "testclient",  # request.client.host from TestClient
        "testserver",  # default Host header from TestClient
    }
)

_ORIGIN_RE = re.compile(
    r"^https?://(127\.0\.0\.1|localhost|\[::1\])(:\d+)?$",
    re.IGNORECASE,
)


def _normalize_host(value: str) -> str:
    host = value.strip().lower()
    if host.startswith("[") and "]" in host:
        inside, _, _rest = host[1:].partition("]")
        return inside
    if host.count(":") == 1:
        return host.split(":", 1)[0]
    if host.count(":") > 1 and host.rsplit(":", 1)[-1].isdigit():
        return host.rsplit(":", 1)[0]
    return host


def is_loopback_host(value: str | None) -> bool:
    if not value:
        return False
    return _normalize_host(value) in _LOOPBACK_HOSTS


def is_loopback_client(request: Request) -> bool:
    client = request.client
    if client is None:
        return False
    return is_loopback_host(client.host)


def is_loopback_origin(origin: str | None) -> bool:
    if not origin:
        return True
    return _ORIGIN_RE.match(origin.strip()) is not None


def token_equals(expected: str, provided: str) -> bool:
    if len(expected) != len(provided):
        return False
    result = 0
    for left, right in zip(expected.encode("utf-8"), provided.encode("utf-8")):
        result |= left ^ right
    return result == 0


def require_loopback_api(request: Request) -> None:
    """Raise 403 unless Host/client (and Origin for mutations) are loopback."""
    if not is_loopback_client(request):
        raise HTTPException(
            status_code=403,
            detail="API only allowed from localhost",
        )

    host = request.headers.get("host")
    if not is_loopback_host(host):
        raise HTTPException(
            status_code=403,
            detail="invalid Host header for local API request",
        )

    if request.method.upper() in _SAFE_METHODS:
        return

    origin = request.headers.get("origin")
    if origin and not is_loopback_origin(origin):
        raise HTTPException(
            status_code=403,
            detail="cross-origin API requests are not allowed",
        )

    referer = request.headers.get("referer")
    if referer:
        parsed = urlparse(referer)
        if parsed.scheme and parsed.netloc:
            referer_origin = f"{parsed.scheme}://{parsed.netloc}"
            if not is_loopback_origin(referer_origin):
                raise HTTPException(
                    status_code=403,
                    detail="cross-origin API requests are not allowed",
                )


def require_local_control(request: Request) -> None:
    """Raise 403 unless this is a trusted local control (shutdown) request."""
    require_loopback_api(request)

    expected = getattr(request.app.state, "control_token", None)
    provided = request.headers.get(CONTROL_TOKEN_HEADER)
    if not expected or not provided or not token_equals(str(expected), provided):
        raise HTTPException(
            status_code=403,
            detail="missing or invalid local control token",
        )


def health_payload(app_state: Any) -> dict[str, str]:
    return {
        "status": "ok",
        "app": "gheymatyar",
        "version": str(getattr(app_state, "app_version", "0.3.0")),
        "control_token": str(getattr(app_state, "control_token", "")),
    }
