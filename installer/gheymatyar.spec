# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for Windows. Build on Windows only:
#   pyinstaller installer/gheymatyar.spec
#
# Prerequisites:
#   1. Build frontend: cd frontend && npm ci && npm run build
#   2. Copy frontend/dist into backend/src/gheymatyar/static
#   3. Run this spec from the repository root on Windows
#
# Note: console=False is intentional for end users. Logging goes to
# %USERPROFILE%\.gheymatyar\gheymatyar.log (see gheymatyar.__main__).

from pathlib import Path

block_cipher = None

REPO = Path(SPECPATH).resolve().parent
BACKEND_SRC = REPO / "backend" / "src"
STATIC = BACKEND_SRC / "gheymatyar" / "static"

datas = []
if STATIC.is_dir():
    datas.append((str(STATIC), "gheymatyar/static"))

hiddenimports = [
    # Application package — required because uvicorn/__main__ import by name
    "gheymatyar",
    "gheymatyar.main",
    "gheymatyar.api",
    "gheymatyar.api.health",
    "gheymatyar.api.sessions",
    "gheymatyar.api.settings",
    "gheymatyar.api.suppliers",
    "gheymatyar.api.mappings",
    "gheymatyar.static_spa",
    # Uvicorn internals (dynamically imported)
    "uvicorn.logging",
    "uvicorn.loops",
    "uvicorn.loops.auto",
    "uvicorn.protocols",
    "uvicorn.protocols.http",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan",
    "uvicorn.lifespan.on",
    # Heavy deps sometimes missed by analysis
    "pdfplumber",
    "fitz",
    "openpyxl",
]

a = Analysis(
    [str(BACKEND_SRC / "gheymatyar" / "__main__.py")],
    pathex=[str(BACKEND_SRC)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="GheymatYar",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="GheymatYar",
)
