"""Fetch one supplier price-list page over HTTPS, only from allowed hosts.

Used only when the user asks for a website price list. It runs one HTTPS
GET with a timeout, a few bounded retries for transient failures, a response
size cap, and a minimum spacing between requests. Every redirect is checked
against the same allow-list, so a page cannot send GheymatYar to another
host. No login, cookies, or JavaScript are used. Only the standard library is
needed, and the Windows build uses the system certificate store.
"""

from __future__ import annotations

import hashlib
import socket
import ssl
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Protocol
from urllib.parse import urlsplit

from gheymatyar import __version__

USER_AGENT = (
    f"GheymatYar/{__version__} (offline price updater; fetched on user request)"
)
DEFAULT_TIMEOUT_SECONDS = 20.0
DEFAULT_MAX_BYTES = 5_000_000
DEFAULT_RETRIES = 2
MIN_SECONDS_BETWEEN_REQUESTS = 3.0
_MAX_REDIRECTS = 3
_RETRY_STATUSES = {500, 502, 503, 504}

_pace_lock = threading.Lock()
_last_request_at = 0.0


class WebsiteFetchError(Exception):
    """A price page could not be fetched safely.

    ``kind`` is one of ``not_allowed``, ``timeout``, ``network``, ``tls``,
    ``http``, ``too_large``, ``content_type``, or ``encoding``.
    """

    def __init__(self, kind: str, message: str, *, status: int | None = None) -> None:
        self.kind = kind
        self.status = status
        super().__init__(message)


@dataclass(frozen=True)
class FetchedPage:
    """One fetched HTML document and where and when it came from."""

    url: str
    final_url: str
    html: str
    fetched_at: str
    last_modified: str | None
    sha256: str


class _Opener(Protocol):
    def open(self, request: urllib.request.Request, timeout: float) -> Any: ...


def check_allowed_url(url: str, allowed_hosts: frozenset[str]) -> None:
    """Raise unless ``url`` is plain HTTPS to one of ``allowed_hosts``."""
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    if (
        parts.scheme != "https"
        or host not in allowed_hosts
        or parts.username
        or parts.password
        or parts.port not in (None, 443)
    ):
        raise WebsiteFetchError("not_allowed", f"refusing to fetch untrusted URL: {url}")


class _AllowListRedirects(urllib.request.HTTPRedirectHandler):
    max_redirections = _MAX_REDIRECTS

    def __init__(self, allowed_hosts: frozenset[str]) -> None:
        super().__init__()
        self._allowed = allowed_hosts

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        check_allowed_url(newurl, self._allowed)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def build_opener(allowed_hosts: frozenset[str]) -> urllib.request.OpenerDirector:
    """HTTPS opener with certificate checks and allow-listed redirects."""
    context = ssl.create_default_context()
    return urllib.request.build_opener(
        urllib.request.HTTPSHandler(context=context),
        _AllowListRedirects(allowed_hosts),
    )


def _pace() -> None:
    """Keep at least a few seconds between requests to a supplier site."""
    global _last_request_at
    with _pace_lock:
        wait = MIN_SECONDS_BETWEEN_REQUESTS - (time.monotonic() - _last_request_at)
        if wait > 0:
            time.sleep(wait)
        _last_request_at = time.monotonic()


def fetch_html(
    url: str,
    *,
    allowed_hosts: frozenset[str],
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    max_bytes: int = DEFAULT_MAX_BYTES,
    retries: int = DEFAULT_RETRIES,
    backoff_seconds: float = 2.0,
    opener: _Opener | None = None,
    pace: bool = True,
) -> FetchedPage:
    """GET ``url`` and return its HTML, or raise :class:`WebsiteFetchError`."""
    check_allowed_url(url, allowed_hosts)
    active = opener or build_opener(allowed_hosts)
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html",
            # urllib does not decompress; ask for a plain body.
            "Accept-Encoding": "identity",
        },
    )
    attempt = 0
    while True:
        attempt += 1
        if pace:
            _pace()
        try:
            return _read_page(active, request, url, allowed_hosts, timeout, max_bytes)
        except WebsiteFetchError as exc:
            transient = exc.kind in {"timeout", "network"} or (
                exc.kind == "http" and exc.status in _RETRY_STATUSES
            )
            if not transient or attempt > retries:
                raise
            time.sleep(backoff_seconds * attempt)


def _read_page(
    opener: _Opener,
    request: urllib.request.Request,
    url: str,
    allowed_hosts: frozenset[str],
    timeout: float,
    max_bytes: int,
) -> FetchedPage:
    try:
        response = opener.open(request, timeout=timeout)
    except WebsiteFetchError:
        raise
    except urllib.error.HTTPError as exc:
        raise WebsiteFetchError(
            "http", f"website answered HTTP {exc.code}", status=exc.code
        ) from exc
    except urllib.error.URLError as exc:
        reason = exc.reason
        if isinstance(reason, WebsiteFetchError):
            raise reason from exc
        if isinstance(reason, ssl.SSLError):
            raise WebsiteFetchError("tls", f"secure connection failed: {reason}") from exc
        if isinstance(reason, (socket.timeout, TimeoutError)):
            raise WebsiteFetchError("timeout", "website did not answer in time") from exc
        raise WebsiteFetchError("network", f"website is unreachable: {reason}") from exc
    except ssl.SSLError as exc:
        raise WebsiteFetchError("tls", f"secure connection failed: {exc}") from exc
    except (socket.timeout, TimeoutError) as exc:
        raise WebsiteFetchError("timeout", "website did not answer in time") from exc
    except OSError as exc:
        raise WebsiteFetchError("network", f"website is unreachable: {exc}") from exc

    with response:
        final_url = response.geturl() or url
        check_allowed_url(final_url, allowed_hosts)
        headers = response.headers
        content_type = (headers.get("Content-Type") or "").lower()
        if not content_type.startswith("text/html"):
            raise WebsiteFetchError(
                "content_type", f"expected an HTML page, got {content_type or 'nothing'}"
            )
        declared = headers.get("Content-Length")
        if declared and declared.isdigit() and int(declared) > max_bytes:
            raise WebsiteFetchError("too_large", "price page is larger than allowed")
        try:
            body = response.read(max_bytes + 1)
        except (socket.timeout, TimeoutError) as exc:
            raise WebsiteFetchError("timeout", "website did not answer in time") from exc
        except OSError as exc:
            raise WebsiteFetchError("network", f"download was interrupted: {exc}") from exc
    if len(body) > max_bytes:
        raise WebsiteFetchError("too_large", "price page is larger than allowed")
    charset = headers.get_content_charset() or "utf-8"
    try:
        html = body.decode(charset)
    except (LookupError, UnicodeDecodeError) as exc:
        raise WebsiteFetchError("encoding", f"price page is not valid {charset}") from exc
    return FetchedPage(
        url=url,
        final_url=final_url,
        html=html,
        fetched_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        last_modified=headers.get("Last-Modified"),
        sha256=hashlib.sha256(body).hexdigest(),
    )
