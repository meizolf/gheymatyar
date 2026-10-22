"""گروه صنعتی تاپ (TOP Industrial Group) price-list processor.

The PDF is a 7-page text list. Each page is one table:

ردیف | نوع جنس | کد | تعداد در کارتن | قیمت (تومان)

Prices use ``.`` as a thousands separator and are printed in Toman.
Carton quantity is not a price and is not multiplied into the amount.
There is no confirmed rule that converts these Toman amounts into the
Rial figures used by other Pioneers sale prices, so every row is flagged
and blocked from automatic export. The stored amount is the printed Toman
value, unchanged.
"""

from __future__ import annotations

import re
from decimal import Decimal
from pathlib import Path
from typing import Any

import pdfplumber

from gheymatyar.domain.supplier_item import SupplierPriceItem
from gheymatyar.services.name_normalization import normalize_product_name
from gheymatyar.suppliers.azin_pipe import fix_reversed_persian
from gheymatyar.suppliers.base import BaseSupplierProcessor, SupplierParseResult
from gheymatyar.suppliers.errors import SupplierPdfError
from gheymatyar.suppliers.textutil import parse_grouped_amount, polish_persian

SUPPLIER_KEY = "top_industrial"
SUPPLIER_DISPLAY_NAME = "گروه صنعتی تاپ"

TOMAN_EXPORT_WARNING = (
    "price is in Toman as printed and was not converted to Rial; "
    "automatic export is blocked until the Pioneers currency rule is confirmed"
)

_CODE_RE = re.compile(r"^(?=.*\d)[0-9A-Za-z]{3,}$")
_SPELLING: tuple[tuple[str, str], ...] = (
    ("کالسیک", "کلاسیک"),
    ("فلاشک", "فلاش"),
    ("فالشک", "فلاش"),
    ("فالش", "فلاش"),
    ("الستیک", "لاستیک"),
    ("طالیی", "طلایی"),
    ("طالمات", "طلا مات"),
    ("سفیدطال", "سفید طلا"),
    ("سفیدکروم", "سفید کروم"),
    ("سفید طال", "سفید طلا"),
)


def _compact(cell: str) -> str:
    return re.sub(r"\s+", "", cell or "")


def _polish_name(raw: str) -> str:
    text = polish_persian(fix_reversed_persian(raw))
    for src, dst in _SPELLING:
        text = text.replace(src, dst)
    text = re.sub(r"(?<!ر)سریز", "سرریز", text)
    text = re.sub(r"(?<![\u0600-\u06FF])طال(?![\u0600-\u06FF])", "طلا", text)
    text = text.replace("شلنگ", "شیلنگ")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _header_map(row: list[Any]) -> dict[str, int]:
    found: dict[str, int] = {}
    for index, cell in enumerate(row):
        compact = _compact(str(cell or ""))
        if not compact:
            continue
        if "تمیق" in compact or "قیمت" in compact:
            found["price"] = index
        elif "دادعت" in compact or "تعداد" in compact:
            found["qty"] = index
        elif compact in {"دک", "کد"} or compact.endswith("دک"):
            found["code"] = index
        elif "فیدر" in compact.replace(" ", "") or "ردیف" in compact:
            found["row"] = index
        elif "عون" in compact or "جنس" in compact:
            found["name"] = index
    return found


def _cells(row: list[Any]) -> list[str]:
    return [str(cell or "").replace("\n", " ").strip() for cell in row]


def _looks_like_code(raw: str) -> bool:
    text = raw.strip()
    if not text or text in {"-", "—", "سفارشی"}:
        return False
    return bool(_CODE_RE.fullmatch(text))


def _name_cell(cells: list[str]) -> str:
    best = ""
    best_score = 0
    for cell in cells:
        if parse_grouped_amount(cell) is not None:
            continue
        fixed = fix_reversed_persian(cell)
        score = len(re.findall(r"[\u0600-\u06FF]", fixed))
        if score > best_score:
            best = cell
            best_score = score
    return best if best_score >= 2 else ""


class TopIndustrialProcessor(BaseSupplierProcessor):
    """Processor for گروه صنعتی تاپ sanitary price lists."""

    supplier_key = SUPPLIER_KEY
    display_name = SUPPLIER_DISPLAY_NAME

    def parse_pdf(self, path: str | Path) -> SupplierParseResult:
        source = Path(path)
        if not source.is_file():
            raise SupplierPdfError(f"PDF not found: {source}")

        items: list[SupplierPriceItem] = []
        warnings: list[str] = []
        page_count = 0
        try:
            with pdfplumber.open(source) as doc:
                page_count = len(doc.pages)
                if page_count == 0:
                    raise SupplierPdfError("PDF has no pages")
                first = doc.pages[0].extract_text() or ""
                if "تاپ" not in first and "پات" not in first:
                    warnings.append(
                        "PDF does not clearly identify as گروه صنعتی تاپ; "
                        "parsing will still be attempted"
                    )
                for page_index, page in enumerate(doc.pages):
                    tables = page.extract_tables() or []
                    if not tables:
                        warnings.append(f"page {page_index + 1}: no table detected")
                        continue
                    page_items, page_warnings = self._parse_table(
                        tables[0], page_number=page_index + 1
                    )
                    items.extend(page_items)
                    warnings.extend(page_warnings)
        except SupplierPdfError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise SupplierPdfError(f"failed to read TOP PDF: {exc}") from exc

        if not items:
            raise SupplierPdfError(
                "No priced products could be extracted from the TOP PDF."
            )

        return SupplierParseResult(
            supplier_key=self.supplier_key,
            supplier_display_name=self.display_name,
            items=items,
            warnings=warnings,
            source_metadata={
                "source_path": str(source),
                "page_count": page_count,
                "item_count": len(items),
                "currency": "toman",
                "pricing_rule": "printed_toman_amount_export_blocked",
                "vat_note": "PDF does not state whether VAT is included",
            },
        )

    def calculate_final_sale_price(self, item: SupplierPriceItem) -> Decimal:
        # Printed Toman amount. Not converted.
        return item.price

    def normalize_supplier_name(self, name: str) -> str:
        return normalize_product_name(name)

    def _parse_table(
        self, table: list[list[Any]], *, page_number: int
    ) -> tuple[list[SupplierPriceItem], list[str]]:
        items: list[SupplierPriceItem] = []
        warnings: list[str] = []
        saw_header = False
        for row_index, row in enumerate(table):
            cells = _cells(list(row or []))
            mapped = _header_map(cells)
            if "price" in mapped and "name" in mapped:
                saw_header = True
                continue
            if not saw_header:
                continue

            price_hits = [
                (index, cell)
                for index, cell in enumerate(cells)
                if parse_grouped_amount(cell) is not None
            ]
            name_raw = _name_cell(cells)
            if len(price_hits) != 1 or not name_raw:
                if any(cells):
                    warnings.append(
                        f"page {page_number}: unreadable TOP row {row_index + 1}"
                    )
                continue
            price_index, price_raw = price_hits[0]
            price = parse_grouped_amount(price_raw)
            name = _polish_name(name_raw)
            if price is None or not name:
                warnings.append(
                    f"page {page_number}: unreadable TOP row {row_index + 1} "
                    f"(name={name_raw!r}, price={price_raw!r})"
                )
                continue

            integers = [
                (index, cell)
                for index, cell in enumerate(cells)
                if index != price_index and re.fullmatch(r"\d{1,4}", cell)
            ]
            row_raw = integers[-1][1] if integers else ""
            qty_raw = ""
            if len(integers) >= 2:
                qty_raw = integers[0][1]
            code = None
            for index, cell in enumerate(cells):
                if index == price_index:
                    continue
                if cell in {row_raw, qty_raw}:
                    continue
                if _looks_like_code(cell):
                    code = cell
                    break
            if not qty_raw:
                custom = next((cell for cell in cells if cell == "سفارشی"), "")
                qty_raw = custom

            display = name if name.startswith("تاپ ") else f"تاپ {name}"
            items.append(
                SupplierPriceItem(
                    supplier_id=self.supplier_key,
                    supplier_code=code,
                    supplier_name=display,
                    price=price,
                    unit="عدد",
                    raw_values={
                        "currency": "toman",
                        "original_price": str(price),
                        "original_price_text": price_raw,
                        "price_basis": "piece",
                        "tax": "not_stated",
                        "page": page_number,
                        "table_row": row_index,
                        "source_row_number": row_raw or None,
                        "package_quantity": qty_raw or None,
                        "review_warnings": [TOMAN_EXPORT_WARNING],
                        "pricing_blockers": [TOMAN_EXPORT_WARNING],
                    },
                )
            )
        return items, warnings
