# Pioneers Excel Workbook Schema

Source of truth for this document:

- Filename: `گزارش لیست کالا - converted.xlsx`
- Inspected: 2026-10-07
- Tool: openpyxl (read-only)
- Original HTML `.xls` re-inspected: 2026-10-20 — `گزارش لیست کالا(1).xls` (UTF-8 BOM HTML `<Table>`, 6775 rows × 40 columns)

The earlier attachment `گزارش لیست کالا - Copy.xls` was an Excel HTML frameset without its companion `_files/` folder and could not be used. The product schema below was first confirmed from the converted `.xlsx`. The Oct 2026 original HTML `.xls` uses the same 40 headers and column order; GheymatYar detects HTML-based `.xls` by content, converts an internal working `.xlsx` copy, then reuses the existing parser/writer. The source `.xls` is never modified.

HTML→XLSX conversion preserves cell values, column order, and row order. It does **not** preserve per-cell HTML styles (B Yekan, borders, background), `dir`/`align` attributes, or the HTML wrapper itself.

Do not treat this document as a guess. Items that could not be confirmed from the file are listed under **Unknowns**.

**Pioneers re-import:** Successful `.xlsx` generation does not prove Pioneers will accept the file. Verify with an actual import into Pioneers.

---

# Workbook Overview

| Property | Observed value |
|---|---|
| Filename | `گزارش لیست کالا - converted.xlsx` |
| Sheet count | 1 |
| Sheet names | `لیست کالا` |
| Active sheet | `لیست کالا` |
| Hidden sheets | none |
| Very hidden sheets | none |
| Workbook protection | none (`security` is empty; no lockStructure / lockWindows) |
| Defined names / named ranges | none |
| Max row | 6772 |
| Max column | 40 (A–AN) |

---

# Relevant Product Sheet

| Sheet | Role |
|---|---|
| `لیست کالا` | Sole sheet; contains the product list header + all product rows |

GheymatYar must use sheet **`لیست کالا`**. There is no alternate product sheet in this workbook.

---

# Header Row

- Header row number: **1**
- Multiple header rows: **no**
- Merged header cells: **none**
- Duplicate headers: **`مرکز پخش`** appears twice (columns **U** and **Y**)
- Blank headers: **none**
- Notable header spelling: product name is stored with tatweel (U+0640) characters as `نـــام کــالا` (not plain `نام کالا`)

## Full header map (row 1)

| Excel Column | # | Header |
|---|---|---|
| A | 1 | انتخاب |
| B | 2 | ردیف |
| C | 3 | فعال |
| D | 4 | کد کالا |
| E | 5 | نـــام کــالا |
| F | 6 | بارکد |
| G | 7 | کد رده |
| H | 8 | نام رده |
| I | 9 | نقطه سفارش |
| J | 10 | حداکثر نقطه سفارش |
| K | 11 | درصد تخفیف |
| L | 12 | درصد تخفیف پنل فروش |
| M | 13 | درصد تخفیف نقدی |
| N | 14 | درصد مالیات |
| O | 15 | درصد پورسانت |
| P | 16 | تعداد آمپر |
| Q | 17 | نرخ آمپر |
| R | 18 | مدت تسویه (روز) |
| S | 19 | سایر مشخصات 2 : |
| T | 20 | سایر مشخصات 1 : |
| U | 21 | مرکز پخش |
| V | 22 | مشخصات فنی : |
| W | 23 | کد تامین کننده : |
| X | 24 | نام تامین کننده : |
| Y | 25 | مرکز پخش |
| Z | 26 | نام مرکز پخش |
| AA | 27 | نرخ جذب |
| AB | 28 | بهای استاندارد |
| AC | 29 | وزن |
| AD | 30 | حجم |
| AE | 31 | عرض |
| AF | 32 | مانده |
| AG | 33 | FormulaResult |
| AH | 34 | نرخ آخرین خرید |
| AI | 35 | نرخ بهای تمام شده |
| AJ | 36 | نرخ خرید روز |
| AK | 37 | نرخ فروش اصلی |
| AL | 38 | نرخ مصرف کننده |
| AM | 39 | نرخ همکاری |
| AN | 40 | نرخ لوله کش |

---

# Column Mapping

| GheymatYar Field | Pioneers Header | Excel Column | Type | Nullable | Notes |
|---|---|---|---|---|---|
| `row_number` | _(Excel row index)_ | — | int | no | Actual worksheet row (header is row 1; first product is row 2). Not column B. |
| `code` | کد کالا | D (4) | string | no | Stored as text in this file. Required. |
| `name` | نـــام کــالا | E (5) | string | no | Exact header includes tatweel chars. Required. |
| `barcode` | بارکد | F (6) | string \| None | yes | Identifier/string. Often blank. |
| `unit` | — | — | — | — | **UNKNOWN** — no dedicated unit column. |
| `sale_price` | نرخ فروش اصلی | AK (37) | Decimal \| None | yes | Mapped by header meaning. |
| `last_purchase_price` | نرخ آخرین خرید | AH (34) | Decimal \| None | yes | Mapped by header meaning. |
| `consumer_price` | نرخ مصرف کننده | AL (38) | Decimal \| None | yes | Header maps clearly; some values look atypical (see Price Columns). |
| `colleague_price` | نرخ همکاری | AM (39) | Decimal \| None | yes | Present; all observed values were `0` in this export. |
| `raw_values` | _(all cells)_ | A–AN | dict | no | Source row snapshot keyed by column letter. |

Unmapped price-like headers (not assigned to `PioneersProduct` fields):

| Header | Column | Reason |
|---|---|---|
| نرخ جذب | AA | No matching domain field |
| بهای استاندارد | AB | No matching domain field |
| نرخ بهای تمام شده | AI | No matching domain field |
| نرخ خرید روز | AJ | No matching domain field |
| نرخ لوله کش | AN | No matching domain field |
| FormulaResult | AG | Conversion artifact; always empty in inspected rows |

---

# Data Row Rules

| Rule | Observation |
|---|---|
| First real product row | **2** |
| Last meaningful product row | **6772** (6771 products) |
| Blank rows | none observed (every data row has a product code) |
| Footer / totals rows | none observed |
| Category / group / separator rows | none observed |
| Non-product rows | none confidently identified |

How the parser distinguishes product rows:

1. After the header row, scan each subsequent row.
2. A row that is **entirely empty** is skipped.
3. A row with **both** `کد کالا` and `نـــام کــالا` empty **but other cells populated** is stored on `invalid_rows` (not silently skipped).
4. A row with a product code and/or name that is missing a required field, has an unusable price, or has an unsafe identifier is stored on `invalid_rows` for review; parsing continues.
5. Column B (`ردیف`) is a sequential index string (`"1"`…`"6771"`). GheymatYar uses the Excel row number, not this display index.

Mapped headers (`کد کالا`, `نـــام کــالا`, `بارکد`, and mapped price headers) must appear **exactly once**. Duplicate mapped headers raise `AmbiguousMappedHeaderError`. Unmapped duplicate headers such as `مرکز پخش` remain allowed (first column wins).

Anomaly in the source file (collected as an invalid row for review):

- Excel row **4755** has code `14867` and barcode `60744` but an **empty** name cell.

---

# Product Code Behavior

| Check | Result |
|---|---|
| Uniqueness | All 6771 codes unique in this file |
| Duplicates | none observed |
| Blanks | none observed |
| Cell type | **text / string** (`data_type='s'`) |
| Numeric cells | none observed for codes |
| Leading zeros | none observed in this export (all codes length 5, range `10001`–`16965`) |
| Whitespace | none observed around codes |
| Number format | `General` |

### Leading-zero protection policy

In this workbook, codes are stored as **strings**. The parser:

1. Reads the cell value without converting through `float`.
2. If the value is already a string, trims surrounding whitespace only and keeps the digits as-is (so `"001234"` stays `"001234"`).
3. If the value is numeric **and** the Excel number format is a **single-section** zero-pad pattern such as `000000`, the parser formats with that width (preserving leading zeros).
4. Multi-section formats (e.g. `000000;000000;"ZERO"`) are **rejected** as unsupported — the parser does not ignore later sections.
5. If the value is numeric with any other unsupported format (e.g. `General`), the row is recorded as invalid — the parser does **not** silently stringify and drop possible leading zeros.
6. Formula cells and Excel error values are rejected as identifiers.

The anonymized fixture includes a leading-zero code to lock this behavior in tests.

---

# Barcode Behavior

| Check | Result |
|---|---|
| Column | F / `بارکد` |
| Non-empty count | 267 / 6771 |
| Blanks | majority empty |
| Duplicates | none among non-empty values |
| Cell type | text / string when present |
| Leading zeros | **yes** — e.g. `015113`, `010452` (57 barcodes start with `0`) |
| Scientific notation | not observed |
| Lengths | mostly 5–6 characters; a few shorter |

### Barcode protection policy

Barcodes are **identifiers**, never money/quantities:

1. Parse as string; never route through binary `float`.
2. Preserve leading zeros when the cell is text, or when a zero-pad number format is present.
3. Unsupported bare-numeric formats → invalid row (not silent coercion).
4. Formula / Excel error cells → invalid row.
5. Empty / whitespace-only → `None`.
6. Do not interpret numeric magnitude; do not strip leading zeros.

---

# Price Columns

Observed storage in this converted file: **all price cells are strings of integer amounts** (number format `General`). No formulas were found in price columns. No decimal points observed.

**Confirmed business rule:** `نرخ فروش اصلی` (`sale_price`, column AK) is stored and exported in **Rial**. GheymatYar never writes any other column. Supplier Toman amounts (e.g. TOP) are converted with Decimal `× 10` before export; original supplier currency/amount remain in metadata only.

| Header | Col | Index | Maps to | Blank | Zero | Negative | Notes |
|---|---|---|---|---|---|---|---|
| نرخ آخرین خرید | AH | 34 | `last_purchase_price` | none (filled) | many `"0"` | none | |
| نرخ فروش اصلی | AK | 37 | `sale_price` | none (filled) | many `"0"` | none | Primary sale price (**Rial**) |
| نرخ مصرف کننده | AL | 38 | `consumer_price` | none (filled) | many `"0"` | **8 negatives** | Header clear; magnitudes sometimes look atypical vs sale price |
| نرخ همکاری | AM | 39 | `colleague_price` | none (filled) | **all** `"0"` | none | Column present but unused in this export |
| نرخ لوله کش | AN | 40 | _(unmapped)_ | none | almost all `"0"` | none | One non-zero sample observed |
| نرخ بهای تمام شده | AI | 35 | _(unmapped)_ | | | | |
| نرخ خرید روز | AJ | 36 | _(unmapped)_ | | | | |
| نرخ جذب | AA | 27 | _(unmapped)_ | | | | |
| بهای استاندارد | AB | 28 | _(unmapped)_ | | | | |

### Decimal parsing policy

1. Empty cell → `None`.
2. Non-empty value → `decimal.Decimal` via string form (`Decimal(str(...))` only after rejecting non-finite / invalid input); never `float(value)` as an intermediate for money.
3. `"0"` is a real value → `Decimal("0")`, not `None`.
4. No silent rounding.

---

# Hidden / Special Workbook Features

| Feature | Observed |
|---|---|
| Hidden rows | none |
| Hidden columns | none |
| Merged cells | none |
| Formulas | none found (including price columns) |
| Conditional formatting | none |
| Data validations | none |
| Frozen panes | none |
| AutoFilter | none |
| Excel tables | none |
| Named ranges | none |
| Sheet protection | False |
| Workbook protection | none |
| Styles | present (e.g. Carlito 11); not required for reading |
| Column A `انتخاب` | always empty in data rows (UI selection column) |
| Column AG `FormulaResult` | always empty; likely HTML/conversion artifact |

---

# Risks for Future Writing (Step 5)

1. **String-stored numbers:** editing prices may need to preserve text-vs-number cell types expected by Pioneers.
2. **Duplicate header `مرکز پخش`:** writers must address columns by letter/index, not header name alone.
3. **Tatweel in name header:** header matching must use the exact string `نـــام کــالا`.
4. **Consumer price data quality:** AL contains negatives and some values that may not be usable consumer prices — UI should warn, not blindly overwrite.
5. **`FormulaResult` column:** leave untouched; purpose unclear.
6. **No formulas today** does not guarantee future exports stay formula-free.
7. **Conversion provenance:** this `.xlsx` was converted from an HTML-style export; a native Pioneers `.xlsx` might differ in cell types (numeric vs text). Re-verify before enabling write mode.
8. **Malformed product rows:** empty name with present code is recorded in `invalid_rows` for review; parsing continues.

---

# Confirmed Assumptions

1. Product data lives only on sheet `لیست کالا`.
2. Headers are exactly on row 1.
3. Required columns for parsing: `کد کالا` (D), `نـــام کــالا` (E).
4. First product data row is row 2.
5. Identifiers (code, barcode) must be handled as strings.
6. Sale / last-purchase / consumer / colleague prices map to AK / AH / AL / AM by header text.
7. Parser must open read-only and must not save the workbook.

---

# Unknowns

1. **`unit`:** no dedicated unit column. `مانده` (AF) embeds quantity + unit text (e.g. `8 عدد`) but is stock-on-hand, not a clean unit field. Left unmapped.
2. Purpose of `FormulaResult` (AG).
3. Encoding / formatting of leading-zero **product codes** (none present in this file; policy tested via fixture only).

# Decisions (user-confirmed)

1. Malformed product rows (missing name/code, bad prices) → keep in `PioneersParseResult.invalid_rows` for review; do not abort the whole parse.
2. Atypical / negative `نرخ مصرف کننده` → later data-quality warnings; still parsed as Decimal here.
3. Inactive products (`فعال` = `False`) → still included in `products`.
4. Converted `.xlsx` cell-type behavior is acceptable for this step.
