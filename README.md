# GheymatYar / Pioneers Price Updater

Local tool for updating **نرخ فروش اصلی** (main sale price) in Pioneers accounting
Excel exports from supplier PDF price lists.

- **Backend (this phase):** Python + FastAPI — complete multi-supplier-ready workflow
- **Frontend:** React + Vite scaffold (not implemented in this phase)
- **Persistence:** SQLite for suppliers, confirmed name mappings, settings
- **Target:** Windows packaging later; local development on macOS

## Repository layout

```
backend/     FastAPI app (src/gheymatyar)
frontend/    React + Vite UI (scaffold)
fixtures/    Anonymized / sample Excel + supplier PDF
docs/        Schema notes + how to add a supplier
scripts/     Dev helpers
installer/   Future Windows packaging
```

## Prerequisites (macOS)

- **Python 3.11+** (Homebrew `python@3.12` recommended)
- Node.js `^20.19.0 || >=22.12.0` (frontend only)

## Backend (macOS)

```bash
cd backend
python3.12 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -e ".[dev]"
uvicorn gheymatyar.main:app --reload --host 127.0.0.1 --port 8765
```

Health: [http://127.0.0.1:8765/api/health](http://127.0.0.1:8765/api/health) → `{"status":"ok"}`

Interactive docs: [http://127.0.0.1:8765/docs](http://127.0.0.1:8765/docs)

SQLite defaults to `~/.gheymatyar/gheymatyar.db` (override with `GHEYMATYAR_DATABASE_URL`
or `GHEYMATYAR_DATA_DIR`).

### Tests

```bash
cd backend
source .venv/bin/activate
pytest
```

### Supported supplier (phase 1)

| Key | Display name | Sample PDF |
|---|---|---|
| `azin_pipe` | آذین لوله | `fixtures/suppliers/458_124550609784457.pdf` |

PDF prices already include 10% VAT; the processor uses **direct replacement**
as the final sale price. See [docs/adding_a_supplier.md](docs/adding_a_supplier.md)
to add another supplier later.

## API endpoints

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/health` | Health check |
| `GET` | `/api/suppliers` | Supported suppliers (UI dropdown) |
| `GET` | `/api/settings` | Read settings |
| `PUT` | `/api/settings` | Update settings |
| `POST` | `/api/sessions` | Create processing session |
| `GET` | `/api/sessions/{id}` | Session summary |
| `POST` | `/api/sessions/{id}/pioneers-excel` | Upload/parse Pioneers Excel |
| `POST` | `/api/sessions/{id}/supplier-pdf` | Upload/parse supplier PDF (`supplier_key` form field) |
| `POST` | `/api/sessions/{id}/match` | Run name matching + price preview |
| `GET` | `/api/sessions/{id}/candidates` | List candidates (`?status=` optional) |
| `GET` | `/api/sessions/{id}/preview` | Matched price-change preview |
| `GET` | `/api/sessions/{id}/pioneers-products/search?q=` | Search Pioneers products |
| `POST` | `/api/sessions/{id}/candidates/{cid}/confirm-mapping` | Manual match + save mapping |
| `POST` | `/api/sessions/{id}/candidates/{cid}/review` | `INCLUDE` / `EXCLUDE` / `APPROVE` |
| `POST` | `/api/sessions/{id}/export` | Generate updated Excel |
| `GET` | `/api/sessions/{id}/download` | Download generated Excel |

### Sample requests

```bash
# Create session
curl -s -X POST http://127.0.0.1:8765/api/sessions
# → {"session_id":"..."}

# Upload Pioneers Excel
curl -s -X POST http://127.0.0.1:8765/api/sessions/$SID/pioneers-excel \
  -F "file=@fixtures/pioneers/pioneers_azin_subset.xlsx"

# Upload Azin PDF
curl -s -X POST http://127.0.0.1:8765/api/sessions/$SID/supplier-pdf \
  -F "supplier_key=azin_pipe" \
  -F "file=@fixtures/suppliers/458_124550609784457.pdf"

# Match
curl -s -X POST http://127.0.0.1:8765/api/sessions/$SID/match \
  -H 'Content-Type: application/json' \
  -d '{"suspicious_percent_threshold":"30"}'

# Confirm a manual mapping
curl -s -X POST http://127.0.0.1:8765/api/sessions/$SID/candidates/$CID/confirm-mapping \
  -H 'Content-Type: application/json' \
  -d '{"pioneers_row_number":42,"save":true}'

# Approve a warned update
curl -s -X POST http://127.0.0.1:8765/api/sessions/$SID/candidates/$CID/review \
  -H 'Content-Type: application/json' \
  -d '{"decision":"APPROVE"}'

# Export + download
curl -s -X POST http://127.0.0.1:8765/api/sessions/$SID/export
curl -s -o updated.xlsx http://127.0.0.1:8765/api/sessions/$SID/download
```

### Sample match candidate (response fragment)

```json
{
  "candidate_id": "…",
  "row_number": 42,
  "pioneers_code": "11489",
  "pioneers_name": "اذین لوله سه لایه 25",
  "supplier_code": "819121025",
  "supplier_name": "اذین لوله سه لایه 25",
  "old_price": "1807190",
  "new_price": "3076040",
  "absolute_change": "1268850",
  "percentage_change": "70.21",
  "match_type": "EXACT_NAME",
  "status": "MATCHED",
  "review_decision": "EXCLUDE",
  "warnings": ["price change 70.21% exceeds 30% threshold"],
  "exportable": false
}
```

## Safety rules

- Original Excel is never overwritten
- Only `نرخ فروش اصلی` is modified
- Fuzzy name matches are never auto-confirmed
- Suspicious price changes (>30% by default) require explicit `APPROVE`
- Export is all-or-nothing validation before write
- Production bind host: `127.0.0.1`

## Frontend (later)

```bash
cd frontend
npm install
npm run dev
```

Dev UI: [http://127.0.0.1:4567](http://127.0.0.1:4567) — Vite proxies `/api` to port `8765`.
