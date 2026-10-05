# GheymatYar / Pioneers Price Updater

Monorepo scaffold for the Pioneers Price Updater desktop-oriented app.

- **Frontend:** React + TypeScript + Vite
- **Backend:** Python + FastAPI
- **Database:** SQLite + SQLAlchemy (wired as dependencies; no business models yet)
- **Target:** Windows exe later; local development on macOS

No Docker, authentication, or Excel/PDF processing in this scaffold.

## Repository layout

```
backend/     FastAPI app (src/gheymatyar)
frontend/    React + Vite UI
fixtures/    Sample data placeholders
scripts/     Dev / build helper scripts
installer/   Future Windows packaging
```

## Prerequisites (macOS)

- **Python 3.11+** (required; macOS system Python 3.9.x will fail with a `requires-python` error). Install via Homebrew and use that interpreter for the venv:

  ```bash
  brew install python@3.12
  ```

  Confirm: `python3.12 --version` should report 3.12.x.
- Node.js 20+ (npm)

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
