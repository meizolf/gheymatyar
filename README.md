# GheymatYar / Pioneers Price Updater

Local tool for updating **نرخ فروش اصلی** (main sale price) in Pioneers accounting
Excel exports from supplier PDF price lists.

- **Backend:** Python + FastAPI — multi-supplier-ready workflow
- **Frontend:** React + Vite — Persian RTL four-step wizard
- **Persistence:** SQLite for suppliers, confirmed name mappings, settings
- **Delivery:** Same-origin localhost app; Windows packaging scripts included

## Repository layout

```
backend/     FastAPI app (src/gheymatyar)
frontend/    React + Vite UI
fixtures/    Anonymized / sample Excel + supplier PDF
docs/        Supplier guide + Windows packaging
scripts/     Dev helpers / launcher
installer/   PyInstaller + Inno Setup (build on Windows)
```

## Prerequisites (macOS development)

- **Python 3.11+** (Homebrew `python@3.12` recommended)
- Node.js `^20.19.0 || >=22.12.0`

## Backend

```bash
cd backend
python3.12 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -e ".[dev]"
uvicorn gheymatyar.main:app --reload --host 127.0.0.1 --port 8765
```

Health: [http://127.0.0.1:8765/api/health](http://127.0.0.1:8765/api/health)

Interactive docs: [http://127.0.0.1:8765/docs](http://127.0.0.1:8765/docs)

SQLite defaults to `~/.gheymatyar/gheymatyar.db` (override with `GHEYMATYAR_DATABASE_URL`
or `GHEYMATYAR_DATA_DIR`).

### Tests

```bash
cd backend && source .venv/bin/activate && pytest
```

## Frontend

```bash
cd frontend
npm install
npm run dev
```

Dev UI: [http://127.0.0.1:4567](http://127.0.0.1:4567) — Vite proxies `/api` to port `8765`.

```bash
npm run typecheck
npm test
npm run build
```

## Production (same origin)

1. `cd frontend && npm run build`
2. Start backend (serves `frontend/dist` automatically when present):

```bash
cd backend && source .venv/bin/activate
python -m gheymatyar
```

Opens [http://127.0.0.1:8765/](http://127.0.0.1:8765/). Override static root with
`GHEYMATYAR_STATIC_DIR`. Bind host remains `127.0.0.1`.

Windows packaging: see [docs/windows_packaging.md](docs/windows_packaging.md).
**Windows EXE must be built on Windows** — not on macOS.

### Supported supplier

| Key | Display name | Sample PDF |
|---|---|---|
| `azin_pipe` | آذین لوله | `fixtures/suppliers/458_124550609784457.pdf` |

See [docs/adding_a_supplier.md](docs/adding_a_supplier.md).

## API endpoints

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/health` | Health check |
| `GET` | `/api/suppliers` | Supported suppliers |
| `GET` | `/api/suppliers/{key}/mappings` | List saved name mappings |
| `PUT` | `/api/suppliers/{key}/mappings/{id}` | Correct a mapping |
| `DELETE` | `/api/suppliers/{key}/mappings/{id}` | Remove a mapping |
| `GET` | `/api/settings` | Read settings |
| `PUT` | `/api/settings` | Update settings |
| `POST` | `/api/sessions` | Create processing session |
| `GET` | `/api/sessions/{id}` | Session summary |
| `POST` | `/api/sessions/{id}/pioneers-excel` | Upload/parse Pioneers Excel |
| `POST` | `/api/sessions/{id}/supplier-pdf` | Upload/parse supplier PDF |
| `POST` | `/api/sessions/{id}/match` | Run name matching + price preview |
| `GET` | `/api/sessions/{id}/candidates` | List candidates (`?status=` optional) |
| `GET` | `/api/sessions/{id}/preview` | Matched price-change preview |
| `GET` | `/api/sessions/{id}/pioneers-products/search?q=` | Search Pioneers products |
| `POST` | `/api/sessions/{id}/candidates/{cid}/confirm-mapping` | Manual match + save mapping |
| `POST` | `/api/sessions/{id}/candidates/{cid}/review` | `INCLUDE` / `EXCLUDE` / `APPROVE` |
| `POST` | `/api/sessions/{id}/export` | Generate updated Excel |
| `GET` | `/api/sessions/{id}/download` | Download generated Excel |

## Safety rules

- Original Excel is never overwritten
- Only `نرخ فروش اصلی` is modified
- Fuzzy name matches are never auto-confirmed
- Suspicious price changes require explicit `APPROVE`
- Export is all-or-nothing validation before write
- Production bind host: `127.0.0.1`

## Verified vs manual

| Capability | Status |
|---|---|
| Full wizard against fixtures via API | Covered by backend + frontend tests |
| Same-origin SPA after `npm run build` | Implemented |
| Windows installer binary | Scripts ready; build on Windows |
| Import into Pioneers desktop app | **Manual** — tool only downloads Excel |
