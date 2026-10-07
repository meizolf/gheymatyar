# GheymatYar / Pioneers Price Updater

Monorepo scaffold for the Pioneers Price Updater desktop-oriented app.

- **Frontend:** React + TypeScript + Vite
- **Backend:** Python + FastAPI (health API + typed domain models)
- **Persistence:** local SQLite via SQLAlchemy 2.x (repositories; no business orchestration yet)
- **Target:** Windows exe later; local development on macOS

No Docker, authentication, PDF processing, matching, or price-update workflow yet. A read-only Pioneers Excel parser is available (no Excel writing yet).

## Repository layout

```
backend/     FastAPI app (src/gheymatyar)
frontend/    React + Vite UI
fixtures/    Sample / anonymized fixtures (incl. Pioneers Excel)
docs/        Workbook schema notes
scripts/     Dev / build helper scripts
installer/   Future Windows packaging
```

## Prerequisites (macOS)

- **Python 3.11+** (required; macOS system Python 3.9.x will fail with a `requires-python` error). Install via Homebrew and use that interpreter for the venv:

  ```bash
  brew install python@3.12
  ```

  Confirm: `python3.12 --version` should report 3.12.x.
- Node.js `^20.19.0 || >=22.12.0` (npm; matches Vite’s engines field)

## Backend (macOS)

If you already created a venv with system Python 3.9, remove it and recreate with 3.12:

```bash
cd backend
rm -rf .venv
python3.12 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -e ".[dev]"
uvicorn gheymatyar.main:app --reload --host 127.0.0.1 --port 8765
```

Always upgrade pip before the editable install. Fresh setup is the same sequence (skip `rm -rf .venv` if there is no existing venv).

Health check: [http://127.0.0.1:8765/api/health](http://127.0.0.1:8765/api/health) → `{"status":"ok"}`

### Persistence (SQLite)

The backend includes a SQLAlchemy persistence layer under `gheymatyar.db` and repositories under `gheymatyar.repositories`. Domain models in `gheymatyar.domain` stay independent of ORM classes.

**Database URL:** pass an explicit SQLite URL when constructing `Database` (for example `sqlite:////tmp/gheymatyar-dev.db`). Importing the package does **not** create a database file. The final Windows application-data path is deferred.

**Transactions:** repositories accept a caller-owned session. Writes flush immediately; on any `SQLAlchemyError` (including constraint and statement/bind failures) the session is rolled back so it remains usable. Prefer `Database.session()` / `session_scope()` for commit-on-success / rollback-on-error scopes.

**Money storage:** prices and percentages are stored as TEXT via a `DecimalAsText` type (not SQLite REAL / SQLAlchemy `Numeric`), so values such as `12345678901234.123456` round-trip exactly as `Decimal`. Non-finite values (`NaN`, infinity) and Python `float` inputs are rejected.

**Foreign keys:** SQLite FK enforcement is enabled on every connection with `PRAGMA foreign_keys=ON`.

**Tests:** use isolated temporary SQLite files (`tmp_path`); they never write to a developer’s real database.

### Backend tests

```bash
cd backend
source .venv/bin/activate
pytest
```

## Frontend (macOS)

In a second terminal:

```bash
cd frontend
npm install
npm run dev
```

Dev UI: [http://127.0.0.1:4567](http://127.0.0.1:4567)

Vite proxies `/api` to the backend on port `8765`, so the health status on the page works during development.

### Frontend production build

```bash
cd frontend
npm run build
```

Output lands in `frontend/dist/`. Later, FastAPI will serve this static build in production.

## Quick local demo

1. Start the backend on port `8765` (commands above).
2. Start the frontend on port `4567`.
3. Open [http://127.0.0.1:4567](http://127.0.0.1:4567) — the page shows **Pioneers Price Updater** and backend status (`ok` / `error` / `loading`).
