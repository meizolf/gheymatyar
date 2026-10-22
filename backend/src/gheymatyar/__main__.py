"""Launch GheymatYar on localhost and open the system browser.

Usage:
    python -m gheymatyar

When packaged with ``console=False`` (Windows windowed EXE), standard streams
may be ``None``. Logging is therefore configured to a user-data log file and
optional console handlers only when streams exist. A normal exit is available
via ``POST /api/shutdown`` (localhost only, control-token protected).
"""

from __future__ import annotations

import json
import logging
import os
import signal
import socket
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

import uvicorn

HOST = "127.0.0.1"
PORT = int(os.environ.get("GHEYMATYAR_PORT", "8765"))
READY_TIMEOUT_SEC = float(os.environ.get("GHEYMATYAR_READY_TIMEOUT", "45"))
READY_POLL_SEC = 0.25
APP_NAME = "gheymatyar"

# Browsers verified for the offline React UI (ES2020+ / modern fetch).
# Must match frontend/vite.config.ts build.target (baseline widely available).
SUPPORTED_BROWSERS = (
    "Microsoft Edge 111+",
    "Google Chrome 111+",
    "Mozilla Firefox 114+",
)


def _data_dir() -> Path:
    override = os.environ.get("GHEYMATYAR_DATA_DIR")
    if override:
        path = Path(override).expanduser()
    else:
        path = Path.home() / ".gheymatyar"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _configure_logging() -> Path:
    """Attach file + safe stream handlers. Never assumes sys.stderr exists."""
    log_path = _data_dir() / "gheymatyar.log"
    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(logging.INFO)
    formatter = logging.Formatter(
        "%(asctime)s %(levelname)s [%(name)s] %(message)s"
    )
    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)

    stream = sys.stderr if sys.stderr is not None else sys.stdout
    if stream is not None:
        try:
            stream_handler = logging.StreamHandler(stream)
            stream_handler.setFormatter(formatter)
            root.addHandler(stream_handler)
        except Exception:  # noqa: BLE001
            pass

    logging.getLogger("uvicorn").handlers = root.handlers[:]
    logging.getLogger("uvicorn.error").handlers = root.handlers[:]
    logging.getLogger("uvicorn.access").handlers = root.handlers[:]
    return log_path


def _parse_health_payload(raw: bytes | str) -> dict[str, object] | None:
    try:
        data = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _is_gheymatyar_health(payload: dict[str, object] | None) -> bool:
    if not payload:
        return False
    return payload.get("status") == "ok" and payload.get("app") == APP_NAME


def _probe_port() -> str:
    """Return ``ours``, ``foreign``, or ``free`` for ``HOST:PORT``."""
    url = f"http://{HOST}:{PORT}/api/health"
    try:
        with urllib.request.urlopen(url, timeout=1.5) as response:
            payload = _parse_health_payload(response.read())
            if _is_gheymatyar_health(payload):
                return "ours"
            return "foreign"
    except (urllib.error.URLError, TimeoutError, OSError):
        pass

    # Nothing answered HTTP — see whether the TCP port is bindable.
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((HOST, PORT))
    except OSError:
        return "foreign"
    finally:
        sock.close()
    return "free"


def _wait_until_ready(
    timeout_sec: float = READY_TIMEOUT_SEC,
) -> dict[str, object] | None:
    deadline = time.monotonic() + timeout_sec
    url = f"http://{HOST}:{PORT}/api/health"
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1.5) as response:
                if not (200 <= getattr(response, "status", 200) < 300):
                    time.sleep(READY_POLL_SEC)
                    continue
                payload = _parse_health_payload(response.read())
                if _is_gheymatyar_health(payload):
                    return payload
        except (urllib.error.URLError, TimeoutError, OSError):
            pass
        time.sleep(READY_POLL_SEC)
    return None


def _detect_windows_browser() -> str | None:
    if sys.platform != "win32":
        return None
    try:
        import winreg  # type: ignore[import-not-found]
    except ImportError:
        return None

    paths = (
        (
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\Shell\Associations\UrlAssociations\http\UserChoice",
            "ProgId",
        ),
        (
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\Shell\Associations\UrlAssociations\https\UserChoice",
            "ProgId",
        ),
    )
    for hive, subkey, name in paths:
        try:
            with winreg.OpenKey(hive, subkey) as key:
                value, _ = winreg.QueryValueEx(key, name)
                if isinstance(value, str) and value.strip():
                    return value.strip()
        except OSError:
            continue
    return None


def _browser_compatibility_notes() -> None:
    """Log clear guidance; do not download or silently require a browser."""
    log = logging.getLogger(__name__)
    log.info(
        "Supported browsers for the offline UI: %s. "
        "Opening the default browser does not prove compatibility — "
        "use a current Edge/Chrome/Firefox build on the target PC.",
        ", ".join(SUPPORTED_BROWSERS),
    )
    prog_id = _detect_windows_browser()
    if prog_id:
        log.info("Windows default HTTP ProgId: %s", prog_id)
        lowered = prog_id.lower()
        if not any(
            token in lowered
            for token in ("chrome", "edge", "firefox", "msedge", "brave")
        ):
            log.warning(
                "Default browser ProgId '%s' may be incompatible. "
                "Install or select one of: %s. GheymatYar does not download a browser.",
                prog_id,
                ", ".join(SUPPORTED_BROWSERS),
            )
    elif sys.platform == "win32":
        log.warning(
            "Could not detect a Windows default browser association. "
            "Install %s, then open http://%s:%s/ manually if needed. "
            "GheymatYar does not download a browser.",
            " / ".join(SUPPORTED_BROWSERS),
            HOST,
            PORT,
        )


def _open_browser(url: str, *, wait_for_ready: bool = True) -> None:
    log = logging.getLogger(__name__)
    if wait_for_ready:
        payload = _wait_until_ready()
        if payload is None:
            log.error(
                "GheymatYar did not become ready within %.0fs on http://%s:%s. "
                "Browser will not be opened. Check the log and port conflicts.",
                READY_TIMEOUT_SEC,
                HOST,
                PORT,
            )
            return

    try:
        opened = webbrowser.open(url)
    except Exception:  # noqa: BLE001
        log.exception(
            "Failed to open a system browser for %s. "
            "Install or repair a supported browser (%s), "
            "then open this address manually: %s",
            url,
            ", ".join(SUPPORTED_BROWSERS),
            url,
        )
        return

    if not opened:
        log.error(
            "No compatible system browser is registered. "
            "Install %s, then open this address manually: %s. "
            "GheymatYar does not download a browser.",
            " / ".join(SUPPORTED_BROWSERS),
            url,
        )
        return

    log.info("Opened browser at %s", url)


def _show_port_conflict_message(kind: str) -> None:
    log = logging.getLogger(__name__)
    if kind == "ours":
        return
    message = (
        f"Port {PORT} on {HOST} is already in use by another application "
        f"(not GheymatYar). Close that program or set GHEYMATYAR_PORT to a "
        f"free port, then try again."
    )
    log.error(message)
    if sys.platform == "win32" and getattr(sys, "frozen", False):
        try:
            import ctypes

            ctypes.windll.user32.MessageBoxW(  # type: ignore[attr-defined]
                0,
                message,
                "قیمت‌یار — پورت اشغال است",
                0x10,  # MB_ICONERROR
            )
        except Exception:  # noqa: BLE001
            pass


def main() -> None:
    log_path = _configure_logging()
    log = logging.getLogger(__name__)
    browser_url = f"http://{HOST}:{PORT}/"

    existing = _probe_port()
    if existing == "ours":
        log.info(
            "GheymatYar is already running on http://%s:%s — reopening browser",
            HOST,
            PORT,
        )
        _browser_compatibility_notes()
        _open_browser(browser_url, wait_for_ready=False)
        return

    if existing == "foreign":
        _show_port_conflict_message("foreign")
        raise SystemExit(2)

    log.info("Starting GheymatYar on http://%s:%s (log=%s)", HOST, PORT, log_path)
    _browser_compatibility_notes()

    from gheymatyar.main import app  # noqa: WPS433

    if not getattr(app.state, "spa_mounted", False):
        log.error(
            "Frontend static files were not found. Rebuild the React UI and "
            "copy frontend/dist into gheymatyar/static before packaging, or set "
            "GHEYMATYAR_STATIC_DIR. The API will still start; the browser UI will "
            "be unavailable."
        )

    config = uvicorn.Config(
        app,
        host=HOST,
        port=PORT,
        log_level="info",
        log_config=None,
        access_log=True,
    )
    server = uvicorn.Server(config)
    app.state.uvicorn_server = server

    threading.Thread(
        target=_open_browser,
        args=(browser_url,),
        daemon=True,
        name="gheymatyar-browser",
    ).start()

    def _handle_signal(signum: int, _frame: object) -> None:
        log.info("Signal %s received — shutting down", signum)
        server.should_exit = True

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(sig, _handle_signal)
        except (ValueError, OSError):
            pass

    try:
        server.run()
    except SystemExit:
        raise
    except OSError as exc:
        # Race: port taken between probe and bind.
        log.error("Failed to bind http://%s:%s: %s", HOST, PORT, exc)
        if _probe_port() == "ours":
            log.info("Another GheymatYar instance is running — reopening browser")
            _open_browser(browser_url, wait_for_ready=False)
            return
        _show_port_conflict_message("foreign")
        raise SystemExit(2) from exc

    log.info("GheymatYar stopped")


if __name__ == "__main__":
    main()
