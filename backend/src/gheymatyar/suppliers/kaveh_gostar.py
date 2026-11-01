"""Kaveh Gostar (کاوه گستر) threaded, saddle, irrigation, and spare-part prices.

The price list is a seven-page Excel export. Each page has a section heading
(«اتصالات پیچی», «اتصالات کمربندی», «اتصالات آبیاری», «ملزومات و قطعات یدکی»)
and several small tables laid out in columns. Each table has its product
title just above it and the columns سایز، تعداد، قیمت (ریال). Saddle tables
add «تعداد پیچ»; the riser table uses «ابعاد (طول)» with one merged size
cell for several lengths.

Columns are found by their header text, not their position. A table without
a size and a price header is skipped. Prices are Rial as printed; the pack
count (تعداد) and bolt count are kept only as reference and never multiply
the price. «*» and other non-amount price cells are skipped and reported.

The company name is only in the page logo image, so detection relies on
product names that appear in this catalog (see :meth:`detection_rules`).
"""

from __future__ import annotations

import re
from pathlib import Path

import pdfplumber
import pymupdf

from gheymatyar.domain.sale_policy import PIONEERS_SALE_CURRENCY
from gheymatyar.domain.supplier_item import SupplierPriceItem
from gheymatyar.suppliers.azin_pipe import fix_reversed_persian
from gheymatyar.suppliers.base import BaseSupplierProcessor, SupplierParseResult
from gheymatyar.suppliers.detection import DetectionRules
from gheymatyar.suppliers.errors import SupplierPdfError
from gheymatyar.suppliers.fitting_sizes import size_groups
from gheymatyar.suppliers.textutil import contains_arabic, parse_grouped_amount, polish_persian

BRAND = "کاوه گستر"
#: Page headings, most specific first, and the word used in product names.
SECTIONS = (
    ("ملزومات و قطعات یدکی", "یدکی"),
    ("اتصالات آبیاری", "آبیاری"),
    ("اتصالات کمربندی", "کمربندی"),
    ("اتصالات پیچی و رزوه ای", "پیچی"),
    ("اتصالات پیچی", "پیچی"),
)
# The cell reads «cm 30» or «30 cm» depending on how the PDF orders it.
_LENGTH = re.compile(r"^(?=.*cm)\D*(\d+)\D*$", re.IGNORECASE | re.DOTALL)


def _clean(cell: str | None) -> str:
    raw = (cell or "").replace("\n", " ").strip()
    return polish_persian(fix_reversed_persian(raw) if contains_arabic(raw) else raw)


def _compact(text: str) -> str:
    return re.sub(r"[\s()‌]", "", text)


def _section(page: pymupdf.Page) -> tuple[str, str]:
    top = polish_persian(page.get_textbox(pymupdf.Rect(0, 0, page.rect.width, 80)))
    compact = _compact(top)
    for heading, word in SECTIONS:
        if _compact(heading) in compact:
            return heading, word
    raise SupplierPdfError(f"Kaveh Gostar page {page.number + 1} has no known section heading")


def _title(page: pymupdf.Page, bbox: tuple[float, float, float, float]) -> str:
    """Persian words just above a table; numbers from a table above are left out."""
    x0, top, x1, _bottom = bbox
    words = page.get_text("words", clip=pymupdf.Rect(x0, top - 20, x1, top - 1))
    words.sort(key=lambda w: -w[0])  # right to left
    kept = [w[4] for w in words if contains_arabic(w[4]) and not re.search(r"\d", w[4])]
    return polish_persian(" ".join(kept))


def _columns(header: list[str | None]) -> dict[str, int] | None:
    names = [_compact(_clean(cell)) for cell in header]
    found: dict[str, int] = {}
    for index, name in enumerate(names):
        if name.startswith("قیمت"):
            found["price"] = index
        elif name == "سایز":
            found["size"] = index
        elif name == "تعدادپیچ":
            found["bolts"] = index
        elif name == "تعداد":
            found["count"] = index
        elif name.startswith("ابعاد"):
            found["length"] = index
    return found if {"price", "size"} <= set(found) else None


class KavehGostarProcessor(BaseSupplierProcessor):
    supplier_key = "kaveh_gostar"
    display_name = "کاوه گستر"

    def detection_rules(self) -> DetectionRules:
        # The brand is only in the logo image; these product names are this
        # catalog's own and appear in no other supported list. Detection reads
        # the first pages only, so pages 1-2 products come first.
        return DetectionRules(
            strong_markers=(
                "اتصال فلنچدار",
                "زانو دوسر ماده",
                "کمربند دوسرنافی",
                "کمربند ناف برنجی",
                "شیرخودکار پلی",
            ),
            weak_markers=("درپوش پلی استال", "مغزی پلی استال", "زانو دوسر نر"),
            websites=(),
        )

    def parse_pdf(self, path: str | Path) -> SupplierParseResult:
        source = Path(path)
        rows: list[dict] = []
        skipped: list[str] = []
        try:
            doc = pymupdf.open(source)
            with pdfplumber.open(source) as pdf:
                for page_index, page in enumerate(pdf.pages):
                    rows.extend(self._page_rows(doc[page_index], page, skipped))
        except SupplierPdfError:
            raise
        except Exception as exc:  # noqa: BLE001 - PDF library failures
            raise SupplierPdfError(f"could not read Kaveh Gostar PDF: {exc}") from exc
        if not rows:
            raise SupplierPdfError("Kaveh Gostar list has no priced products")
        items = self._items(rows)
        warnings = [f"skipped {len(skipped)} cells that are not a clear price"] if skipped else []
        return SupplierParseResult(
            supplier_key=self.supplier_key,
            supplier_display_name=self.display_name,
            items=items,
            warnings=warnings + skipped[:20],
            source_metadata={"source": "pdf", "file": source.name, "item_count": len(items)},
        )

    def _page_rows(self, mpage: pymupdf.Page, page, skipped: list[str]) -> list[dict]:
        heading, section = _section(mpage)
        out: list[dict] = []
        for table in page.find_tables():
            cells = table.extract()
            columns = _columns(cells[0]) if cells else None
            if columns is None:
                continue  # notes and logos, not a price table
            title = _title(mpage, table.bbox)
            if not title:
                raise SupplierPdfError(
                    f"Kaveh Gostar page {page.page_number}: a price table has no title"
                )
            carried_size: str | None = None
            for row_number, row in enumerate(cells[1:], start=2):
                size_raw = _clean(row[columns["size"]]) if row[columns["size"]] else ""
                if size_raw:
                    carried_size = size_raw
                elif "length" in columns:
                    size_raw = carried_size or ""  # merged size cell over several lengths
                price_raw = (row[columns["price"]] or "").strip()
                if not size_raw and not price_raw:
                    continue
                amount = parse_grouped_amount(price_raw)
                where = f"page {page.page_number} «{title}» {size_raw}"
                if amount is None:
                    skipped.append(f"{where}: {price_raw!r}")
                    continue
                sizes = size_groups(size_raw)
                if not sizes:
                    skipped.append(f"{where}: size not readable")
                    continue
                length = None
                if "length" in columns:
                    match = _LENGTH.search(_clean(row[columns["length"]]))
                    if not match:
                        skipped.append(f"{where}: length not readable")
                        continue
                    length = match.group(1)
                out.append({
                    "page": page.page_number, "heading": heading, "section": section,
                    "title": title, "sizes": sizes, "length": length, "price": amount,
                    "count": _clean(row[columns["count"]]) if "count" in columns else None,
                    "bolts": _clean(row[columns["bolts"]]) if "bolts" in columns else None,
                    "row": row_number,
                })
        return out

    def _items(self, rows: list[dict]) -> list[SupplierPriceItem]:
        # «زانو», «رابط», «سه راه» are threaded fittings on page 1 and different
        # irrigation fittings on page 6: such titles carry their section word.
        sections_by_title: dict[str, set[str]] = {}
        for row in rows:
            sections_by_title.setdefault(row["title"], set()).add(row["section"])
        items: list[SupplierPriceItem] = []
        seen: dict[str, object] = {}
        for row in rows:
            qualifier = (
                f" {row['section']}"
                if len(sections_by_title[row["title"]]) > 1 and row["section"] not in row["title"]
                else ""
            )
            size = "×".join(row["sizes"])
            name = f"{BRAND} {row['title']}{qualifier} سایز {size}"
            if row["length"]:
                name += f" طول {row['length']} cm"
            if name in seen:
                if seen[name] != row["price"]:
                    raise SupplierPdfError(f"Kaveh Gostar lists «{name}» twice at different prices")
                continue  # a table continued in the next page column
            seen[name] = row["price"]
            items.append(
                SupplierPriceItem(
                    supplier_id=self.supplier_key,
                    supplier_name=name,
                    price=row["price"],
                    raw_values={
                        "currency": PIONEERS_SALE_CURRENCY,
                        "price_basis": "printed",
                        "tax": "not_stated",
                        "page": row["page"],
                        "section": row["heading"],
                        "table_title": row["title"],
                        "package_count": row["count"],
                        "bolt_count": row["bolts"],
                        "table_row": row["row"],
                    },
                )
            )
        return items
