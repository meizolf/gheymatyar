"""Serve the React production build as a same-origin SPA."""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles


def resolve_static_dir() -> Path | None:
    """Locate frontend dist directory (env override, then repo-relative)."""
    override = os.environ.get("GHEYMATYAR_STATIC_DIR")
    if override:
        path = Path(override).expanduser().resolve()
        return path if path.is_dir() else None

    # backend/src/gheymatyar/static_spa.py → repo root
    repo_dist = (
        Path(__file__).resolve().parents[3] / "frontend" / "dist"
    )
    if repo_dist.is_dir():
        return repo_dist

    # PyInstaller / installed layout: sibling static/ next to package
    bundled = Path(__file__).resolve().parent / "static"
    if bundled.is_dir():
        return bundled

    return None


def mount_frontend(app: FastAPI, static_dir: Path | None = None) -> bool:
    """Mount SPA assets and HTML5 history fallback. Returns True if mounted."""
    root = static_dir or resolve_static_dir()
    if root is None:
        return False

    index = root / "index.html"
    if not index.is_file():
        return False

    assets = root / "assets"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

    @app.get("/")
    async def spa_index() -> FileResponse:
        return FileResponse(index)

    _RESERVED = frozenset(
        {"api", "docs", "redoc", "openapi.json", "assets"}
    )

    @app.get("/{full_path:path}")
    async def spa_fallback(full_path: str) -> FileResponse:
        first = full_path.split("/", 1)[0]
        if first in _RESERVED or full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="not found")
        candidate = (root / full_path).resolve()
        try:
            candidate.relative_to(root.resolve())
        except ValueError as exc:
            raise HTTPException(status_code=404, detail="not found") from exc
        if candidate.is_file():
            return FileResponse(candidate)
        # SPA client-side routes (e.g. /mappings, /settings)
        return FileResponse(index)

    return True
