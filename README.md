# GheymatYar / Pioneers Price Updater

Local tool for updating **نرخ فروش اصلی** (main sale price) in Pioneers accounting
Excel exports from supplier PDF price lists.

- **Backend:** Python + FastAPI — multi-supplier-ready workflow
- **Frontend:** React + Vite — Persian RTL four-step wizard
- **Persistence:** SQLite for suppliers, confirmed name mappings, ignored products, settings
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

- **Python 3.11 or 3.12** (Homebrew `python@3.12` recommended; Windows packaging pins 3.12)
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

Interactive OpenAPI docs are **disabled by default** (offline / no CDN). Enable with
`GHEYMATYAR_ENABLE_DOCS=1` if needed during development.

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

### Offline Windows installer

See [docs/windows_packaging.md](docs/windows_packaging.md) for the full guide.

- **Artifact:** one `GheymatYarSetup.exe` (no Python/Node on the target PC)
- **Build:** Windows only — local `scripts/windows/build_installer.ps1` or GitHub Actions
  workflow **Windows Offline Installer** (`.github/workflows/windows-installer.yml`)
- **Download from CI:** Actions → workflow run → Artifacts → **`GheymatYarSetup`**
- **Data:** mappings and ignored products survive upgrades in `%USERPROFILE%\.gheymatyar\`

macOS cannot produce the Windows EXE; use the Actions artifact or a Windows build host.

### Supplier support

Only `نرخ فروش اصلی` is written, and only on rows the user has explicitly approved when the new price is numerically different. The output workbook contains those product rows and the required headers, not the rest of the uploaded catalog. That column is always **Rial**; there is no currency or price-basis setting. The only setting is the warning threshold (`suspicious_percent_threshold`). Amounts use `Decimal` — never float. Carton, length, branch, roll, and package quantities are never multiplied into the sale price, and VAT is not invented. A per-metre price is never written onto a branch unit such as `شاخه 6 متری`. Genuine extraction, duplicate-name, identity, and ambiguous-column blockers remain. The default download is Pioneers' own `.xls` format: a UTF-8 HTML table with the same markup, header row, and column order as a Pioneers `گزارش لیست کالا.xls` export, not a renamed `.xlsx`. Each exported row keeps every original field; only `نرخ فروش اصلی` changes. The verified `.xlsx` it is rendered from stays available with `?format=xlsx`. Import into the Pioneers desktop application still has to be checked by hand.

| Key | List | Price handling |
|---|---|---|
| `azin_pipe` | آذین لوله | Printed Rial, 10% VAT included. Direct replacement. |
| `top_industrial` | گروه صنعتی تاپ | Printed Toman → Rial with `× 10` (e.g. 3,240,000 Toman → 32,400,000 Rial). Carton qty not multiplied. |
| `dina_polymer` | دینا پلیمر | Printed Rial. Pipe/drip prices stay per meter; fittings per piece. Fitting `#N/A` column is the price; drip table uses labeled `قیمت` (not adjacent `#N/A`). |
| `newpipe` | نیوپایپ | Printed Rial, 10% VAT included. Package length is not multiplied. Same name with different prices is blocked. |
| `abrahan_pipe` | آبراهان | Printed cash Rial. `موجود` rows are skipped. VAT is not stated. |
| `kian` | کیان | Printed Toman → Rial with a single `× 10`. Package quantity is not multiplied. |

Pars Plast, PG 234 (Polymer Golpayegan), and Kaveh Gostar are **not supported**. Their pages are image-only or the embedded font does not expose the printed prices. Offline Persian OCR is not bundled, and Windows offline OCR has not been verified, so those keys stay unregistered and return HTTP 400.

Windows onedir packaging and import of the updated workbook into the Pioneers desktop app are not verified from this macOS tree.

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
| `POST` | `/api/sessions/{id}/supplier-pdf/detect` | Upload PDF and detect supplier (no price parse) |
| `POST` | `/api/sessions/{id}/supplier-pdf/confirm` | Confirm supplier and parse prices |
| `POST` | `/api/sessions/{id}/supplier-pdf` | Upload/parse with explicit `supplier_key` (API confirmation) |
| `POST` | `/api/sessions/{id}/match` | Run name matching + price preview |
| `GET` | `/api/sessions/{id}/candidates` | List candidates (`?status=` optional) |
| `GET` | `/api/sessions/{id}/preview` | Matched price-change preview |
| `GET` | `/api/sessions/{id}/pioneers-products/search?q=` | Search Pioneers products |
| `POST` | `/api/sessions/{id}/candidates/{cid}/confirm-mapping` | Manual match + save mapping |
| `POST` | `/api/sessions/{id}/candidates/{cid}/ignore` | Soft-delete (ignore) a supplier product |
| `POST` | `/api/sessions/{id}/candidates/{cid}/restore` | Restore an ignored supplier product |
| `POST` | `/api/sessions/{id}/candidates/{cid}/review` | `INCLUDE` / `EXCLUDE` / `APPROVE` |
| `POST` | `/api/sessions/{id}/export` | Generate updated Excel (Pioneers `.xls` and `.xlsx`) |
| `GET` | `/api/sessions/{id}/download` | Download the Pioneers `.xls`; `?format=xlsx` for the `.xlsx` |

## Safety rules

- Original Excel is never overwritten
- Only `نرخ فروش اصلی` is modified
- Fuzzy name matches are never auto-confirmed
- A saved mapping wins over an exact name and is stored per supplier variant (normalized name, supplier code, and unit). Mappings saved before variants were distinguished are kept, but they are not applied automatically: the original code and unit are unknown, so each variant must be confirmed. If the Pioneers product is missing or no longer unique, the row stays unmatched until the user maps it again. Export and download recheck saved decisions and do not update a product from an obsolete target or a deletion made in another session
- Deleting a product on the matching page is a persistent ignore for that supplier and product identity (normalized name, supplier code, and unit). It does not remove the PDF row or any Pioneers product, and ignored rows are excluded from price review and Excel export. A later list that changes the code or unit is a different product and does not reuse the decision. Decisions are never shared across suppliers
- Suspicious price changes require explicit `APPROVE`
- Supplier auto-detection is a suggestion only; prices are never parsed or matched until the user confirms the company
- Export is all-or-nothing validation before write
- Production bind host: `127.0.0.1`

## Verified vs manual

| Capability | Status |
|---|---|
| Full wizard against fixtures via API | Covered by backend + frontend tests |
| Same-origin SPA after `npm run build` | Implemented |
| Windows installer binary | Spec + Inno + Actions workflow; download `GheymatYarSetup` artifact |
| Import into Pioneers desktop app | **Manual** — tool only downloads Excel |
