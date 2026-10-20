# Windows Packaging

GheymatYar ships as a **local Windows application**: one installer starts the
FastAPI backend on `127.0.0.1`, serves the React UI from the same origin, and
opens the default browser. Users do **not** install Node.js, Python, or npm.

## Important constraints

| Constraint | Detail |
|---|---|
| Build host | **Windows only** (or a Windows CI runner). macOS PyInstaller does not produce Windows executables. |
| Network | Bind host is hard-coded to `127.0.0.1`. Do not expose the app publicly. |
| Mapping data | SQLite at `%USERPROFILE%\.gheymatyar\gheymatyar.db` — outside the install directory so upgrades preserve mappings. |
| Artifacts on this repo | Spec + Inno scripts are provided. **This macOS development machine cannot produce the `.exe` / Setup binary.** |

## Build steps (on Windows)

### 1. Build the frontend

```bat
cd frontend
npm ci
npm run build
```

### 2. Bundle static files into the Python package

```bat
rmdir /s /q backend\src\gheymatyar\static
xcopy /e /i frontend\dist backend\src\gheymatyar\static
```

### 3. Install packaging tools

```bat
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -U pip
pip install -e .
pip install pyinstaller
```

Install [Inno Setup 6](https://jrsoftware.org/isinfo.php) separately.

### 4. PyInstaller

From the repository root:

```bat
pyinstaller installer\gheymatyar.spec
```

Output: `dist\GheymatYar\GheymatYar.exe` plus bundled dependencies.

### 5. Inno Setup installer

```bat
iscc installer\gheymatyar.iss
```

Output: `dist\installer\GheymatYarSetup-0.3.0.exe`

## Runtime behaviour

1. User launches `GheymatYar.exe` (or Start Menu shortcut).
2. Process starts Uvicorn on `http://127.0.0.1:8765`.
3. System browser opens to that URL.
4. Logs are written to `%USERPROFILE%\.gheymatyar\gheymatyar.log` (windowed EXE has no console; Uvicorn is configured with `log_config=None` so missing `stderr` does not crash startup).
5. Normal exit: use **خروج از برنامه** in the UI (`POST /api/shutdown` on localhost) or end the process from Task Manager.
6. Temporary processing sessions are in-memory; **confirmed name mappings** persist in SQLite under the user profile.

**Packaging status:** scripts are ready. An actual Windows installer has **not** been built or verified on this development machine.

## Smoke test after install

1. Launch the app; browser shows the Persian wizard.
2. Upload `fixtures\pioneers\pioneers_azin_subset.xlsx`.
3. Select آذین لوله; upload `fixtures\suppliers\458_124550609784457.pdf`.
4. Run matching → preview → export → download Excel.
5. Restart the app; open **نگاشت‌های ذخیره‌شده** and confirm prior mappings remain.
6. Confirm the original Pioneers Excel file on disk is unchanged.

## Verified vs manual

| Item | Status |
|---|---|
| Frontend + API on macOS (Vite + uvicorn) | Verified in development |
| FastAPI SPA mount + `python -m gheymatyar` | Implemented; verify after `npm run build` |
| Windows PyInstaller / Inno artifacts | **Not built on macOS** — requires Windows |
| Import into Pioneers accounting software | **Manual** — app only produces an Excel file |

## Troubleshooting

- **Blank page after install:** ensure `frontend/dist` was copied to `gheymatyar/static` before PyInstaller.
- **Port in use:** set `GHEYMATYAR_PORT` or stop the other process on 8765.
- **Lost mappings after upgrade:** check `%USERPROFILE%\.gheymatyar\` was not deleted manually.
