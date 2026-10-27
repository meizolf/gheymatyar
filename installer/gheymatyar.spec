# -*- mode: python ; coding: utf-8 -*-
# PyInstaller onedir spec for Windows. Build on Windows only:
#   pyinstaller installer/gheymatyar.spec
#
# Prerequisites:
#   1. Build frontend: cd frontend && npm ci && npm run build
#   2. Copy frontend/dist into backend/src/gheymatyar/static
#   3. Run this spec from the repository root on Windows
#
# Note: console=False is intentional for end users. Logging goes to
# %USERPROFILE%\.gheymatyar\gheymatyar.log (see gheymatyar.__main__).
# UPX is disabled: it can break signed/native DLLs (pdfium, OpenSSL, VC++).

from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_dynamic_libs

block_cipher = None

REPO = Path(SPECPATH).resolve().parent
BACKEND_SRC = REPO / "backend" / "src"
STATIC = BACKEND_SRC / "gheymatyar" / "static"

if not STATIC.is_dir() or not (STATIC / "index.html").is_file():
    raise SystemExit(
        "Missing frontend static build at backend/src/gheymatyar/static/index.html. "
        "Run scripts/windows/prepare_static.ps1 (or npm run build + copy) before "
        "PyInstaller."
    )

datas = [(str(STATIC), "gheymatyar/static")]
binaries = []
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
    "gheymatyar.parsers",
    "gheymatyar.parsers.pioneers_excel_parser",
    "gheymatyar.parsers.pioneers_html_xls",
    "gheymatyar.parsers.workbook_format",
    "gheymatyar.suppliers",
    "gheymatyar.suppliers.azin_pipe",
    "gheymatyar.suppliers.pars_plast",
    "gheymatyar.suppliers.website_fetch",
    "gheymatyar.suppliers.registry",
    # Uvicorn internals (dynamically imported)
    "uvicorn.logging",
    "uvicorn.loops",
    "uvicorn.loops.auto",
    "uvicorn.protocols",
    "uvicorn.protocols.http",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.http.h11_impl",
    "uvicorn.protocols.http.httptools_impl",
    "uvicorn.protocols.websockets",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan",
    "uvicorn.lifespan.on",
    # Heavy / native deps sometimes missed by analysis
    "pdfplumber",
    "pdfminer",
    "pdfminer.high_level",
    "pypdfium2",
    "pypdfium2_raw",
    "PIL",
    "openpyxl",
    "cryptography",
    "multipart",
    # Excel 97–2003 (.xls) export writer and its read-back verification.
    "xlwt",
    "xlrd",
]

# Bundle package data + native libraries for PDF/crypto stacks.
for pkg in (
    "pdfplumber",
    "pdfminer",
    "pypdfium2",
    "pypdfium2_raw",
    "PIL",
    "cryptography",
    "openpyxl",
):
    try:
        pkg_datas, pkg_binaries, pkg_hidden = collect_all(pkg)
    except Exception as exc:  # noqa: BLE001
        raise SystemExit(f"PyInstaller collect_all({pkg!r}) failed: {exc}") from exc
    datas += pkg_datas
    binaries += pkg_binaries
    hiddenimports += pkg_hidden

# pymupdf ships native extensions; keep it for transitive completeness even though
# the Azin parser uses pdfplumber today.
try:
    binaries += collect_dynamic_libs("pymupdf")
    hiddenimports += ["pymupdf", "fitz"]
except Exception:
    pass

a = Analysis(
    [str(BACKEND_SRC / "gheymatyar" / "__main__.py")],
    pathex=[str(BACKEND_SRC)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Keep the onedir bundle lean — unused on Windows production launch.
        "tkinter",
        "unittest",
        "test",
        "tests",
        "pytest",
        "IPython",
        "notebook",
    ],
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
    upx=False,
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
    upx=False,
    upx_exclude=[],
    name="GheymatYar",
)
