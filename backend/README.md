# GheymatYar backend

Python package under `src/gheymatyar`.

## Run (macOS)

```bash
cd backend
source .venv/bin/activate   # or create with python3.12 -m venv .venv
pip install -e ".[dev]"
uvicorn gheymatyar.main:app --reload --host 127.0.0.1 --port 8765
```

## Tests

```bash
pytest
```

## Architecture

- `parsers/` — Pioneers Excel reader
- `services/` — matching, price validation, Excel writer, sessions, orchestration
- `suppliers/` — pluggable PDF processors (`azin_pipe` today)
- `repositories/` — SQLite persistence (suppliers, name mappings, settings)
- `api/` — FastAPI routes (thin controllers)

See root [README](../README.md) and [docs/adding_a_supplier.md](../docs/adding_a_supplier.md).
