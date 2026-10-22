"""Packaging path / launcher helpers used by the Windows offline installer."""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

import pytest

from gheymatyar import __main__ as launcher
from gheymatyar.static_spa import resolve_static_dir


def test_resolve_static_dir_env_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<html></html>", encoding="utf-8")
    monkeypatch.setenv("GHEYMATYAR_STATIC_DIR", str(dist))
    assert resolve_static_dir() == dist.resolve()


def test_resolve_static_dir_missing_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GHEYMATYAR_STATIC_DIR", str(tmp_path / "missing"))
    assert resolve_static_dir() is None


def test_resolve_static_dir_meipass(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    meipass = tmp_path / "meipass"
    static = meipass / "gheymatyar" / "static"
    static.mkdir(parents=True)
    (static / "index.html").write_text("<html>packaged</html>", encoding="utf-8")
    monkeypatch.delenv("GHEYMATYAR_STATIC_DIR", raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(meipass), raising=False)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "GheymatYar.exe"))
    resolved = resolve_static_dir()
    assert resolved == static.resolve()


def test_wait_until_ready_success(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {"status": "ok", "app": "gheymatyar", "version": "0.3.0"}

    class _Resp:
        status = 200

        def read(self) -> bytes:
            return json.dumps(payload).encode()

        def __enter__(self) -> "_Resp":
            return self

        def __exit__(self, *args: object) -> None:
            return None

    monkeypatch.setattr(launcher.urllib.request, "urlopen", lambda *a, **k: _Resp())
    assert launcher._wait_until_ready(timeout_sec=1.0) == payload


def test_wait_until_ready_rejects_foreign_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Resp:
        status = 200

        def read(self) -> bytes:
            return b'{"status":"ok","app":"other"}'

        def __enter__(self) -> "_Resp":
            return self

        def __exit__(self, *args: object) -> None:
            return None

    monkeypatch.setattr(launcher.urllib.request, "urlopen", lambda *a, **k: _Resp())
    monkeypatch.setattr(launcher.time, "sleep", lambda _s: None)
    assert launcher._wait_until_ready(timeout_sec=0.01) is None


def test_wait_until_ready_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(*_a: object, **_k: object) -> None:
        raise launcher.urllib.error.URLError("down")

    monkeypatch.setattr(launcher.urllib.request, "urlopen", _boom)
    monkeypatch.setattr(launcher.time, "sleep", lambda _s: None)
    assert launcher._wait_until_ready(timeout_sec=0.01) is None


def test_probe_port_ours(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Resp:
        def read(self) -> bytes:
            return b'{"status":"ok","app":"gheymatyar"}'

        def __enter__(self) -> "_Resp":
            return self

        def __exit__(self, *args: object) -> None:
            return None

    monkeypatch.setattr(launcher.urllib.request, "urlopen", lambda *a, **k: _Resp())
    assert launcher._probe_port() == "ours"


def test_probe_port_foreign_http(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Resp:
        def read(self) -> bytes:
            return b'{"status":"ok"}'

        def __enter__(self) -> "_Resp":
            return self

        def __exit__(self, *args: object) -> None:
            return None

    monkeypatch.setattr(launcher.urllib.request, "urlopen", lambda *a, **k: _Resp())
    assert launcher._probe_port() == "foreign"


def test_open_browser_logs_when_no_browser(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(
        launcher,
        "_wait_until_ready",
        lambda *_a, **_k: {"status": "ok", "app": "gheymatyar"},
    )
    monkeypatch.setattr(launcher.webbrowser, "open", lambda _url: False)
    with caplog.at_level(logging.ERROR):
        launcher._open_browser("http://127.0.0.1:8765/")
    assert any("No compatible system browser" in r.message for r in caplog.records)
    assert any("does not download a browser" in r.message for r in caplog.records)


def test_open_browser_skips_when_server_not_ready(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(launcher, "_wait_until_ready", lambda *_a, **_k: None)
    opened: list[str] = []
    monkeypatch.setattr(
        launcher.webbrowser, "open", lambda url: opened.append(url) or True
    )
    with caplog.at_level(logging.ERROR):
        launcher._open_browser("http://127.0.0.1:8765/")
    assert opened == []
    assert any("did not become ready" in r.message for r in caplog.records)


def test_data_dir_override(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "custom-data"
    monkeypatch.setenv("GHEYMATYAR_DATA_DIR", str(target))
    path = launcher._data_dir()
    assert path == target
    assert path.is_dir()


def test_data_dir_default_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("GHEYMATYAR_DATA_DIR", raising=False)
    monkeypatch.setattr(launcher.Path, "home", staticmethod(lambda: tmp_path))
    path = launcher._data_dir()
    assert path == tmp_path / ".gheymatyar"
    assert path.is_dir()


def test_shutdown_message_mentions_exe(client) -> None:
    token = client.get("/api/health").json()["control_token"]
    response = client.post(
        "/api/shutdown",
        headers={"X-GheymatYar-Token": token},
    )
    assert response.status_code == 400
    detail = response.json()["detail"]
    assert "GheymatYar.exe" in detail
    assert "python -m gheymatyar" in detail


def test_docs_disabled_by_default(client) -> None:
    assert client.get("/docs").status_code == 404
    assert client.get("/redoc").status_code == 404
    assert client.get("/openapi.json").status_code == 404
