# GheymatYar backend

Python package under `src/gheymatyar`.

## Run (macOS)

```bash
cd backend
source .venv/bin/activate   # or create with python3.12 -m venv .venv
pip install -e ".[dev]"
uvicorn gheymatyar.main:app --reload --host 127.0.0.1 --port 8765
```

Production-style (serves `frontend/dist` when built, opens browser):

```bash
# from repo root: cd frontend && npm run build
python -m gheymatyar
```

## Tests

```bash
pytest
```

Fixture smoke (no browser):

```bash
python ../scripts/e2e_fixture_check.py
```

## Architecture

- `parsers/` — Pioneers Excel reader
- `services/` — matching, price validation, Excel writer, sessions, orchestration
- `suppliers/` — pluggable PDF processors (`azin_pipe` today)
- `repositories/` — SQLite persistence (suppliers, name mappings, ignored products, settings)
- `api/` — FastAPI routes (thin controllers)
- `static_spa.py` — React production build mount + SPA fallback

See root [README](../README.md), [docs/adding_a_supplier.md](../docs/adding_a_supplier.md),
and [docs/windows_packaging.md](../docs/windows_packaging.md).
