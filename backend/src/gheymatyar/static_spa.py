"""Serve the React production build as a same-origin SPA."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles


def resolve_static_dir() -> Path | None:
    """Locate frontend dist directory (env override, then bundled / repo paths)."""
    override = os.environ.get("GHEYMATYAR_STATIC_DIR")
    if override:
        path = Path(override).expanduser().resolve()
        return path if path.is_dir() else None

    candidates: list[Path] = []

    # PyInstaller onedir / onefile extraction root
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidates.append(Path(meipass) / "gheymatyar" / "static")

    # Frozen EXE next to collected package data (onedir layout)
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).resolve().parent
        candidates.append(exe_dir / "gheymatyar" / "static")
        candidates.append(exe_dir / "_internal" / "gheymatyar" / "static")

    # Installed / source layout: sibling static/ next to this module
    candidates.append(Path(__file__).resolve().parent / "static")

    # Development: repo frontend/dist (backend/src/gheymatyar → repo root)
    candidates.append(Path(__file__).resolve().parents[3] / "frontend" / "dist")

    for candidate in candidates:
        if candidate.is_dir() and (candidate / "index.html").is_file():
            return candidate

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
