"""SPA static mount behaves correctly when dist is present."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from gheymatyar.main import create_app


def test_spa_serves_index_and_preserves_api(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dist = tmp_path / "dist"
    assets = dist / "assets"
    assets.mkdir(parents=True)
    (dist / "index.html").write_text(
        "<!doctype html><html><body>قیمت‌یار</body></html>",
        encoding="utf-8",
    )
    (assets / "app.js").write_text("console.log(1)", encoding="utf-8")

    monkeypatch.setenv("GHEYMATYAR_STATIC_DIR", str(dist))

    app = create_app(
        database_url=f"sqlite:///{tmp_path / 'spa.db'}",
        mount_spa=True,
    )
    assert app.state.spa_mounted is True

    with TestClient(app) as client:
        health = client.get("/api/health")
        assert health.status_code == 200
        assert health.json()["status"] == "ok"

        index = client.get("/")
        assert index.status_code == 200
        assert "قیمت‌یار" in index.text

        # Client-side route refresh
        mappings = client.get("/mappings")
        assert mappings.status_code == 200
        assert "قیمت‌یار" in mappings.text

        asset = client.get("/assets/app.js")
        assert asset.status_code == 200
