"""Launch GheymatYar on localhost and open the system browser.

Usage:
    python -m gheymatyar

When packaged with ``console=False`` (Windows windowed EXE), standard streams
may be ``None``. Logging is therefore configured to a user-data log file and
optional console handlers only when streams exist. A normal exit is available
via ``POST /api/shutdown`` (localhost only).
"""

from __future__ import annotations

import logging
import os
import signal
import sys
import threading
import time
import webbrowser
from pathlib import Path

import uvicorn

HOST = "127.0.0.1"
PORT = int(os.environ.get("GHEYMATYAR_PORT", "8765"))


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

    # Prevent uvicorn from re-adding broken default handlers later.
    logging.getLogger("uvicorn").handlers = root.handlers[:]
    logging.getLogger("uvicorn.error").handlers = root.handlers[:]
    logging.getLogger("uvicorn.access").handlers = root.handlers[:]
    return log_path


def _open_browser() -> None:
    time.sleep(0.8)
    webbrowser.open(f"http://{HOST}:{PORT}/")


def main() -> None:
    log_path = _configure_logging()
    logging.getLogger(__name__).info(
        "Starting GheymatYar on http://%s:%s (log=%s)", HOST, PORT, log_path
    )

    # Import the app object directly so PyInstaller freezes gheymatyar.main.
    from gheymatyar.main import app  # noqa: WPS433

    config = uvicorn.Config(
        app,
        host=HOST,
        port=PORT,
        log_level="info",
        log_config=None,  # use our handlers; avoids stderr crash when None
        access_log=True,
    )
    server = uvicorn.Server(config)
    app.state.uvicorn_server = server

    threading.Thread(target=_open_browser, daemon=True).start()

    def _handle_signal(signum: int, _frame: object) -> None:
        logging.getLogger(__name__).info("Signal %s received — shutting down", signum)
        server.should_exit = True

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(sig, _handle_signal)
        except (ValueError, OSError):
            pass

    server.run()
    logging.getLogger(__name__).info("GheymatYar stopped")


if __name__ == "__main__":
    main()
