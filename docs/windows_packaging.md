# Windows Packaging — Offline Installer

GheymatYar ships as a **local Windows application**: one installer EXE starts the
FastAPI backend on `127.0.0.1`, serves the React UI from the same origin, and
opens the default browser after the **GheymatYar** health identity is confirmed.
Users do **not** install Node.js, Python, npm, or any online prerequisites.

## Deliverable

| Artifact | Location |
|---|---|
| Offline installer | `dist/installer/GheymatYarSetup.exe` |
| Checksums | `dist/installer/GheymatYarSetup.exe.sha256.txt`, `SHA256SUMS` |
| Unpacked onedir app (debug) | `dist/GheymatYar/GheymatYar.exe` + `_internal/` |

Internally PyInstaller uses **`onedir`**. Inno Setup packages that folder into one
Setup EXE. UPX is disabled.

## Important constraints

| Constraint | Detail |
|---|---|
| Build host | **Windows x64 only** (or GitHub Actions `windows-latest`). macOS/Linux cannot produce the Windows EXE. |
| Python for packaging | **3.12.x x64** (CI pins **3.12.10**). Runtime is bundled. |
| Network at runtime | Bind host `127.0.0.1` only. |
| Mapping data | `%USERPROFILE%\.gheymatyar\gheymatyar.db` — outside the install dir (survives upgrade/uninstall). |
| Logs | `%USERPROFILE%\.gheymatyar\gheymatyar.log` |
| Browser | See [Browser requirements](#browser-requirements). The app **never** downloads a browser. |
| Docs UI | `/docs` and `/redoc` are **disabled** (they load CDN assets). Opt-in: `GHEYMATYAR_ENABLE_DOCS=1`. |
| Fonts | System stack only (`Segoe UI`, Tahoma, …) — no Google Fonts. |
| Offline target | No VC++ redistributable installer, WebView2 bootstrapper, winget, or choco on the target PC. VC++ runtime DLLs must be **inside** the onedir bundle. |

## Browser requirements

Opening the default browser is **not** the same as compatibility.

| Browser | Minimum version (aligned with Vite `build.target`) |
|---|---|
| Microsoft Edge (Chromium) | **111+** |
| Google Chrome | **111+** |
| Mozilla Firefox | **114+** |

These match `frontend/vite.config.ts` (`chrome111` / `edge111` / `firefox114`, Vite 8
baseline-widely-available). **Not supported:** Internet Explorer, legacy EdgeHTML.

### How the app checks

1. On launch, the launcher logs the Windows default HTTP ProgId (when detectable) and the supported browser list.
2. Readiness waits for `/api/health` with `"app":"gheymatyar"` (not merely HTTP 200).
3. The React UI shows a Persian banner if the engine looks unsupported.
4. If no browser can be opened, the log tells the user to install a supported browser and open `http://127.0.0.1:8765/` manually.

### Offline target checklist

Before smoke-testing an offline Windows 10 PC, confirm **one** of Edge 111+, Chrome 111+, or Firefox 114+ is installed **on that machine**. GheymatYar will not fetch a browser.

## Duplicate launches and ports

| Situation | Behaviour |
|---|---|
| GheymatYar already running on the port | Second launch detects `/api/health` identity, **reopens the browser**, exits without binding again. |
| Unrelated process on the port | Clear error in the log (and a Windows message box for the frozen EXE). Exit code `2`. |
| Ready check | Must see `app=gheymatyar` — a random HTTP service on the port is treated as foreign. |

## Local control security

`POST /api/shutdown` requires:

1. Loopback client address  
2. Loopback `Host` header  
3. Matching `X-GheymatYar-Token` (from `/api/health`)  
4. Reject foreign `Origin` / `Referer` when present  

CORS alone does **not** stop a foreign-origin simple form POST; the token does.

## Reproducible pins

| Pin | Value |
|---|---|
| App version | `0.3.0` |
| Runtime deps | `backend/pyproject.toml` + `backend/requirements-windows.txt` |
| Packaging tools | PyInstaller `6.22.3`, hooks-contrib `2026.8` |
| Inno Setup (CI) | `6.7.3` (installer SHA-256 pinned; **no** `ISCC --version` — unsupported on 6.7.3; CI checks uninstall `DisplayVersion`) |
| Frontend lockfile | `frontend/package-lock.json` |

## Local Windows build

### Prerequisites (build machine only)

- Windows 10/11 x64
- Python **3.12** x64
- Node.js 20.19+ or 22.12+
- [Inno Setup 6.7.3](https://jrsoftware.org/isinfo.php)

### One-shot

```powershell
.\scripts\windows\build_installer.ps1
```

Produces `dist\installer\GheymatYarSetup.exe` plus checksum files. The smoke step
runs the packaged EXE with a **sanitized PATH** (bundle + `System32` only) so
missing bundled VC++ DLLs fail closed.

## GitHub Actions

Workflow: [`.github/workflows/windows-installer.yml`](../.github/workflows/windows-installer.yml)

### Steps

1. Checkout  
2. Python 3.12.10 x64 + Node 22  
3. Install Inno Setup 6.7.3; verify SHA-256; confirm registry `DisplayVersion=6.7.3` (do **not** run `ISCC -?` / `--version` — exits 1 on 6.7.3 and fails Actions)  
4. Frontend: `npm ci` → typecheck → test (fail-fast)  
5. Embed SPA (`prepare_static.ps1`)  
6. Pin-install Python deps + editable backend  
7. Backend `pytest`  
8. PyInstaller onedir  
9. `verify_bundle.ps1` — SPA offline assets, AMD64 PE, pdfium, full native import closure (every `.dll`/`.pyd`/`.exe`; VC++ redist DLLs required when imported)  
10. `smoke_packaged.ps1` — xlsx + HTML `.xls` (convert+compare all sheets/formulas), mapping save → restart → persist, API shutdown must exit (no silent force-kill success)  
11. Compile installer; write size + SHA-256 sidecar files  
12. Upload artifact **`GheymatYarSetup`** (`GheymatYarSetup.exe` + checksums)

### Download

GitHub → **Actions** → **Windows Offline Installer** → **Artifacts** → **`GheymatYarSetup`**.

Retain the published `GheymatYarSetup.exe` together with its `sha256` and byte size from the artifact / workflow log.

## Packaged smoke coverage

| Check | Covered in CI smoke |
|---|---|
| Health identity `app=gheymatyar` | Yes |
| SPA without Google Fonts / CDN refs | Yes |
| Shutdown without token → 403 | Yes |
| `.xlsx` Excel + Azin PDF → export | Yes |
| HTML-based `.xls` + PDF → export | Yes |
| Source file SHA unchanged | Yes |
| Export: only `نرخ فروش اصلی` cells change (xlsx) | Yes (`compare_export.py`) |
| Export sale-price cell matches candidate (xls) | Yes |
| Explicit mapping save + EXE restart + same mapping | Yes |
| Sanitized PATH (no VS redist dirs) | Yes |

## Manual Windows 10 / Pioneers verification

> **Status on this development machine (macOS): unverified.**  
> An actual Windows 10 x64 offline PC was **not** available here. Until the
> checklist below is executed on such a machine (using a CI-built installer),
> Windows 10 compatibility and Pioneers reimport remain **unverified**.

After downloading `GheymatYarSetup.exe` from Actions:

1. Record **bytes** and **SHA-256** from `GheymatYarSetup.exe.sha256.txt`; confirm the EXE matches.  
2. Copy the installer to an **offline** Windows 10 x64 PC that already has Edge 111+ / Chrome 111+ / Firefox 114+.  
3. Install → confirm desktop + Start Menu shortcuts.  
4. Launch → no console window; browser opens the Persian UI.  
5. Run Excel + supplier PDF → export → download.  
6. Exit via **خروج از برنامه**; relaunch; mappings remain.  
7. Launch a second shortcut while running → browser reopens; no second server.  
8. Upgrade-install over the same AppId; mappings remain.  
9. Uninstall; confirm `%USERPROFILE%\.gheymatyar\gheymatyar.db` remains; reinstall; mappings load.  
10. **Pioneers desktop reimport** of the downloaded Excel — **manual / unverified** until an accountant PC is used.

## Performance note

Matching ~6,700 synthetic rows took about **26 seconds on macOS** in one
review measurement. Windows packaged performance is **unverified**; no matching
algorithm changes were made for this packaging pass.

## Troubleshooting

| Symptom | Check |
|---|---|
| Blank page | Static embed before PyInstaller; `_internal/gheymatyar/static/index.html` |
| Port in use (foreign) | Close the other app or set `GHEYMATYAR_PORT` |
| Second launch does nothing useful | Should reopen browser if health identity matches; check log |
| Browser incompatible banner | Install Edge/Chrome/Firefox at the versions above |
| PDF parse fails only in EXE | `verify_bundle.ps1` — pdfium + VC++ DLLs must be in the bundle |
| `verify_bundle` flags `bcryptprimitives.dll` | That DLL is a Windows CNG system dependency (not redistributable). It belongs on the OS allowlist, not in the onedir tree. |
| Shutdown 403 | UI must send `X-GheymatYar-Token` from `/api/health` |

## Verified vs unverified

| Item | Status |
|---|---|
| Backend/frontend unit tests (incl. security + packaging helpers) | Verified on macOS CI-equivalent local runs |
| Windows installer build + packaged smoke | Designed for Actions `windows-latest` (run there to produce the EXE) |
| Offline install on older Windows 10 x64 | **Unverified** until performed on a real PC |
| Pioneers accounting reimport | **Unverified** / manual |
| Matching performance on Windows | **Unverified** |
