"""Texa (صنایع شیرسازی تکسا) valve price list, three pages.

Each page has one product table: ردیف، نام کالا، کد، وزن، تعداد در کارتن،
قیمت (ریال), and a product photo column. Page 3 adds a small spare-parts
table (ردیف، نام، قیمت) without codes; its names cite the valve code they
fit («مهره واسطه کد 700»), which stays part of the name.

Prices are Rial and use «/» between thousands (10/970/000 = 10,970,000).
They are never converted, never multiplied by the carton count or weight,
and a dashed price is skipped. Codes are not unique in this list (700 is
both «شیر شوفاژ» and «شیر و زانو شوفاژ»), so products are never merged by
code: the name, code, and price stay together per row.

A few name cells use font glyphs that have no text mapping. The letters
are restored from :data:`_CID_GLYPHS`; the stacked or Unicode fraction
cells are taken from :data:`_CELL_REPAIRS` (exactly as printed). Any other
unmapped glyph skips the row with a warning instead of guessing.
"""

from __future__ import annotations

import re
from decimal import Decimal
from pathlib import Path

import pdfplumber

from gheymatyar.domain.sale_policy import PIONEERS_SALE_CURRENCY
from gheymatyar.domain.supplier_item import SupplierPriceItem
from gheymatyar.services.name_normalization import normalize_digits
from gheymatyar.suppliers.azin_pipe import fix_reversed_persian
from gheymatyar.suppliers.base import BaseSupplierProcessor, SupplierParseResult
from gheymatyar.suppliers.detection import DetectionRules
from gheymatyar.suppliers.errors import SupplierPdfError
from gheymatyar.suppliers.textutil import contains_arabic, parse_grouped_amount, polish_persian

BRAND = "تکسا"
SPARE_PARTS = "قطعات یدکی"
# Glyph ids without a text mapping in this list's font (visual order cells).
_CID_GLYPHS = {
    "(cid:5505)": "ر",
    "(cid:5524)": "و",
    "(cid:5593)": "پ",
    "(cid:6292)": "ج",
    "(cid:6353)": "ی",
}
# Cells whose fractions are drawn as stacked or Unicode glyphs, so their
# text order cannot be recovered: raw cell text → the name as printed.
_CELL_REPAIRS = {
    "(cid:2869)\n”\n١ رتولف\n(cid:2872)\n( يجنرب پاپوس)": 'فلوتر 1 1/4" سوپاپ برنجی',
    "¾ ½\nو رتولف يپوت": "توپی فلوتر 1/2 و 3/4",
    '¼ "١ و "١ رتولف يپوت': 'توپی فلوتر 1" و 1 1/4"',
}
_SPELLING = (
    (re.compile(r"\s+ژ(?=\s|$)"), "ژ"),  # «شوفا ژ»: a split final letter
    (re.compile(r"پ(?:یکج|کیچ|یکچ)(?!\S)"), "پکیج"),  # not «روپیچ»
    (re.compile(r"زانوشوفاژ"), "زانو شوفاژ"),
    (re.compile(r"غیر\s+گازی"), "غیرگازی"),
    (re.compile(r"^شیر(?=[^\s\d])"), "شیر "),
    (re.compile(r"([؀-ۿ])(\d)"), r"\1 \2"),
    (re.compile(r"(\d|\")([؀-ۿ])"), r"\1 \2"),
    (re.compile(r"\s*\*\s*"), "×"),
)
_FRACTIONS = {"½": "1/2", "¾": "3/4", "¼": "1/4"}


def _amount(cell: str | None) -> Decimal | None:
    return parse_grouped_amount((cell or "").replace("/", ","))


def _plain(cell: str | None) -> str:
    return re.sub(r"\s", "", polish_persian(fix_reversed_persian(cell or "")))


def product_name(cell: str | None) -> str | None:
    """The full Persian name from a (visually reversed) name cell, or None."""
    raw = (cell or "").strip()
    if raw in _CELL_REPAIRS:
        return _CELL_REPAIRS[raw]
    for glyph, letter in _CID_GLYPHS.items():
        raw = raw.replace(glyph, letter)
    if "(cid:" in raw:
        return None
    lines = [fix_reversed_persian(line) for line in raw.split("\n") if line.strip()]
    text = normalize_digits(" ".join(lines))
    # The inch mark lands before the number in the reversed text: «"1» → «1"».
    text = re.sub(r'(?<![\d/])"(\d+(?:/\d+)?)', r'\1"', text.replace("”", '"'))
    for glyph, fraction in _FRACTIONS.items():
        text = text.replace(glyph, f" {fraction} ")
    text = polish_persian(text.replace("(", " ").replace(")", " "))
    for pattern, replacement in _SPELLING:
        text = pattern.sub(replacement, text)
    return " ".join(text.split()) or None


class TexaProcessor(BaseSupplierProcessor):
    supplier_key = "texa"
    display_name = "صنایع شیرسازی تکسا"

    def detection_rules(self) -> DetectionRules:
        # The company name is only in the logo image; «تکسا» appears as text
        # in «طرح تکسا» on page 3.
        return DetectionRules(
            strong_markers=("تکسا",),
            weak_markers=("F46", "فلوتر", "شوفاژ"),
            websites=(),
        )

    def parse_pdf(self, path: str | Path) -> SupplierParseResult:
        source = Path(path)
        rows: list[dict] = []
        skipped: list[str] = []
        try:
            with pdfplumber.open(source) as pdf:
                for page in pdf.pages:
                    for table in page.find_tables():
                        rows.extend(self._table_rows(table.extract(), page.page_number, skipped))
        except SupplierPdfError:
            raise
        except Exception as exc:  # noqa: BLE001 - pdfplumber failures
            raise SupplierPdfError(f"could not read Texa PDF: {exc}") from exc
        if not rows:
            raise SupplierPdfError("Texa list has no priced products")
        names = [row["name"] for row in rows]
        if len(names) != len(set(names)):
            repeated = sorted({n for n in names if names.count(n) > 1})
            raise SupplierPdfError(f"Texa list repeats product names: {repeated[:3]}")
        items = [self._item(row) for row in rows]
        warnings = [f"skipped {len(skipped)} rows without a clear price or name"] if skipped else []
        return SupplierParseResult(
            supplier_key=self.supplier_key,
            supplier_display_name=self.display_name,
            items=items,
            warnings=warnings + skipped[:20],
            source_metadata={"source": "pdf", "file": source.name, "item_count": len(items)},
        )

    def _table_rows(self, cells: list[list[str | None]], page: int, skipped: list[str]):
        if not cells:
            return []
        header = [_plain(cell) for cell in cells[0]]
        columns = {
            key: next((i for i, text in enumerate(header) if text.startswith(word)), None)
            for key, word in (("price", "قیمت"), ("name", "نام"), ("code", "کد"),
                              ("carton", "تعداددر"), ("weight", "وز"))
        }
        if columns["price"] is not None and columns["name"] is not None:
            body, section = cells[1:], None
        elif len(cells[0]) == 3 and _amount(cells[0][0]) is not None:
            # Spare parts: price, name, row — no header and no code column.
            columns = {"price": 0, "name": 1, "code": None, "carton": None, "weight": None}
            body, section = cells, SPARE_PARTS
        else:
            raise SupplierPdfError(f"Texa page {page}: table columns not recognized")
        out = []
        for row in body:
            def cell(key: str) -> str | None:
                index = columns[key]
                return row[index] if index is not None else None

            code = normalize_digits((cell("code") or "").strip()) or None
            name = product_name(cell("name"))
            where = f"page {page} code {code or '-'}"
            amount = _amount(cell("price"))
            if amount is None:
                skipped.append(f"{where}: price {(cell('price') or '').strip()!r}")
                continue
            if name is None:
                skipped.append(f"{where}: name has unmapped glyphs")
                continue
            if code is not None and not code.isdigit():
                raise SupplierPdfError(f"Texa {where}: code is not a number")
            out.append({
                "name": f"{BRAND} {name}", "price": amount, "code": code, "page": page,
                "section": section, "carton": normalize_digits((cell("carton") or "").strip()),
                "weight": normalize_digits((cell("weight") or "").strip()),
            })
        return out

    def _item(self, row: dict) -> SupplierPriceItem:
        return SupplierPriceItem(
            supplier_id=self.supplier_key,
            supplier_name=row["name"],
            supplier_code=row["code"],
            price=row["price"],
            raw_values={
                "currency": PIONEERS_SALE_CURRENCY,
                "price_basis": "printed",
                "tax": "not_stated",
                "page": row["page"],
                "section": row["section"],
                "carton_count": row["carton"] or None,
                "weight": row["weight"] or None,
            },
        )
