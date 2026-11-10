"""نیوپایپ (NewPipe / Gitikala) five-layer pipe price-list processor.

The sample is an 11-page two-column Excel export. pdfplumber keeps each
product's code, size, package counts, and price on one row, while Persian
labels are character-reversed. Package counts (meters in a coil, pieces in
a carton) are not prices and are not multiplied.

The footer states that listed Rial prices already include 10% VAT. Those
amounts are used as printed. No extra tax is added.

The same supplier also publishes a two-page accessories list («لیست قیمت
ملزومات سیستم لوله کشی تاسیسات پلیمری», Gitikala/SGP branded) with two
tables side by side under red section headings. Its text layer is in
logical order, so it is read from PyMuPDF characters placed into cells by
position under the header row; see :func:`_accessory_rows`.
"""

from __future__ import annotations

import re
from decimal import Decimal
from pathlib import Path
from typing import Any

import pdfplumber
import pymupdf

from gheymatyar.domain.sale_policy import PIONEERS_SALE_CURRENCY, PRICE_BASIS_PRINTED
from gheymatyar.domain.supplier_item import SupplierPriceItem
from gheymatyar.services.name_normalization import normalize_product_name
from gheymatyar.suppliers.azin_pipe import fix_reversed_persian
from gheymatyar.suppliers.base import BaseSupplierProcessor, SupplierParseResult
from gheymatyar.suppliers.detection import DetectionRules
from gheymatyar.suppliers.errors import SupplierPdfError
from gheymatyar.suppliers.textutil import contains_arabic, parse_grouped_amount, polish_persian

SUPPLIER_KEY = "newpipe"
SUPPLIER_DISPLAY_NAME = "نیوپایپ"

_CODE_RE = re.compile(r"^\d{6,}$")

# pdfplumber column indexes for the two sides of the sheet.
_LEFT = {"price": 0, "pack": 1, "qty": 2, "size": 3, "code": 4}
_RIGHT = {"price": 7, "pack": 8, "qty": 9, "size": 10, "code": 11}

_SKIP_CATEGORY = (
    "قیمت",
    "ریال",
    "تاریخ",
    "گیتی",
    "http",
    "اطلاع",
    "page",
)


def _cell(row: list[Any], index: int) -> str:
    if index >= len(row) or row[index] is None:
        return ""
    return str(row[index]).replace("\n", " ").strip()


def _category_label(raw: str) -> str | None:
    if not raw or raw in {"-", "—"}:
        return None
    if parse_grouped_amount(raw) is not None:
        return None
    fixed = polish_persian(fix_reversed_persian(raw))
    fixed = re.sub(r"\s*-\s*-\s*", " ", fixed)
    fixed = re.sub(r"\s+", " ", fixed).strip(" -")
    if not fixed or not contains_arabic(fixed):
        return None
    # Page furniture only. Product headings such as «سه راهی صفحه دار» stay.
    if re.fullmatch(r"صفحه(?:\s*\d+)?", fixed):
        return None
    lowered = fixed.lower()
    if any(fragment in lowered for fragment in _SKIP_CATEGORY):
        return None
    if re.fullmatch(r"[\d\s*+/.\-]+", fixed):
        return None
    return fixed


# Mixed fraction (1 1/4), proper fraction (3/4), or whole number — kept as one group.
_DIM = r"(?:\d+\s+\d+/\d+|\d+/\d+|\d+)"
# pdfplumber dumps reversed Persian connection labels.
_CONN_LABEL = r"(?:چیپوت|چیپور|توپیچ|روپیچ)"
_CONN_PAIR_RE = re.compile(
    rf"^[\s\"'″]*(?P<a>{_DIM})\s*(?P<la>{_CONN_LABEL})\s*\*\s*"
    rf"(?P<b>{_DIM})\s*(?P<lb>{_CONN_LABEL})\s*$"
)
# Reducing caps: one labelled connection + one unlabelled overall size.
# Example raw: ``" 1/2 چیپوت * 1 1/4`` → overall 1 1/4, توپیچ 1/2.
_CONN_SINGLE_LEFT_RE = re.compile(
    rf"^[\s\"'″]*(?P<conn>{_DIM})\s*(?P<label>{_CONN_LABEL})\s*\*\s*"
    rf"(?P<overall>{_DIM})\s*$"
)
_CONN_SINGLE_RIGHT_RE = re.compile(
    rf"^[\s\"'″]*(?P<overall>{_DIM})\s*\*\s*"
    rf"(?P<conn>{_DIM})\s*(?P<label>{_CONN_LABEL})\s*$"
)
_CONN_LIKE_RE = re.compile(rf"(?:چیپوت|چیپور).*\*|.*\*.*(?:چیپوت|چیپور)")

_SIZE_AMBIGUOUS = (
    "male/female connection dimensions could not be resolved reliably; "
    "automatic export is blocked until the size is confirmed"
)


def _connection_label(raw: str) -> str | None:
    if raw in {"چیپور", "روپیچ"}:
        return "روپیچ"
    if raw in {"چیپوت", "توپیچ"}:
        return "توپیچ"
    return None


def _normalize_dim(raw: str) -> str:
    return re.sub(r"\s+", " ", raw.strip())


def _strip_plan_marker(text: str) -> tuple[str, str]:
    plan = ""
    if "حرط" in text or re.search(r"طرح", text):
        plan = " طرح B"
        text = re.sub(r"\bB\b", " ", text)
        text = re.sub(r"[()]\s*حرط\s*[()]?", " ", text)
        text = re.sub(r"[()]\s*طرح\s*[()]?", " ", text)
    return re.sub(r"\s+", " ", text).strip(), plan


def _parse_connection_size(raw: str) -> str | None:
    """Parse روپیچ/توپیچ sizes from the raw LTR cell before reversing tokens.

    ``fix_reversed_persian`` splits mixed fractions such as ``1 1/4`` across the
    ``*`` boundary. Parse dimensions while they are still attached to each label.

    Dual-labelled pairs become ``روپیچ …*توپیچ …``. Single-labelled reducing
    caps keep the unlabelled overall size without inventing a male/female label.
    """
    text, plan = _strip_plan_marker(raw.replace("\n", " ").strip())

    match = _CONN_PAIR_RE.fullmatch(text)
    if match is not None:
        left_label = _connection_label(match.group("la"))
        right_label = _connection_label(match.group("lb"))
        if left_label is None or right_label is None or left_label == right_label:
            return None
        parts = {
            left_label: _normalize_dim(match.group("a")),
            right_label: _normalize_dim(match.group("b")),
        }
        return f"روپیچ {parts['روپیچ']}*توپیچ {parts['توپیچ']}{plan}"

    single = _CONN_SINGLE_LEFT_RE.fullmatch(text) or _CONN_SINGLE_RIGHT_RE.fullmatch(
        text
    )
    if single is None:
        return None
    label = _connection_label(single.group("label"))
    if label is None:
        return None
    overall = _normalize_dim(single.group("overall"))
    connection = _normalize_dim(single.group("conn"))
    # Unlabelled side is the overall body size — never invent روپیچ/توپیچ.
    return f"{overall}*{label} {connection}{plan}"


def _clean_size(raw: str) -> tuple[str | None, str | None]:
    """Return ``(display_size, pricing_blocker)``.

    Connection sizes are parsed from the raw cell so mixed fractions stay with
    the correct male/female side. Unresolvable connection-like cells are blocked.
    """
    if not raw or raw.strip() in {"-", "—", "*"}:
        return None, None

    connected = _parse_connection_size(raw)
    if connected is not None:
        return connected, None
    if _CONN_LIKE_RE.search(raw.replace("\n", " ")):
        return None, _SIZE_AMBIGUOUS

    text = polish_persian(fix_reversed_persian(raw))
    text = text.replace('"', " ").replace("″", " ")
    text = re.sub(r"\s*-\s*-\s*", " ", text)
    text = re.sub(r"(\d+)\s*mm", r"\1mm", text, flags=re.IGNORECASE)
    match = re.fullmatch(
        r"طول توپیچ(?:\s*mm)?\s*(\d+)\s*(\d/\d)",
        text.strip(),
    )
    if match is None:
        match = re.fullmatch(
            r"طول توپیچ mm\s*(\d+)\s*(\d/\d)",
            text.strip(),
        )
    if match:
        text = f"{match.group(2)} طول توپیچ {match.group(1)}mm"
    text = re.sub(r"\s+", " ", text).strip(" -")
    return (text or None), None


# --- Accessories list ------------------------------------------------------
#: Title of the accessories list. Identity needs it *and* the NewPipe
#: «نیوباکس» heading: Gitikala/SGP branding alone is shared with other lists.
ACCESSORIES_TITLE = "ملزومات سیستم لوله کشی تاسیسات پلیمری"
ACCESSORIES_HEADING = "نیوباکس"
_HEADING_RED = 0xC00000
_ACC_HEADERS = {
    "price": "قیمت(ریال)",
    "carton": "تعداد در کارتن",
    "box": "تعداد در جعبه",
    "image": "تصویر",
}
_ACC_CODE_RE = re.compile(r"\d{9}")
# The lam-alef ligature is extracted as «ال» in this list's font.
_ACC_FIXES = (("پالستیک", "پلاستیک"), ("اقالم", "اقلام"))
_ROW_TOLERANCE = 18  # points; rows are ~39 pt apart


def _acc_text(raw: str) -> str:
    """Clean one accessories cell: glyph fixes, spacing, inch marks, dashes."""
    text = polish_persian(raw)
    for src, dst in _ACC_FIXES:
        text = text.replace(src, dst)
    text = re.sub(r"[\u064B-\u0652]", "", text)  # harakat («اُرینگ»)
    text = re.sub(r'["″()]', " ", text)
    # «تخت50» → «تخت 50», «قطرM8» → «قطر M8».
    text = re.sub(
        r"(?<=[\u0600-\u06FF])(?=[A-Za-z\d])|(?<=[A-Za-z\d])(?=[\u0600-\u06FF])", " ", text
    )
    # Separator dashes («شکل - 49x27»), not joined codes such as «WT-D».
    text = re.sub(r"(?<!\S)-|-(?!\S)", " ", text)
    text = re.sub(r"(\d)\s+mm\b", r"\1mm", text)
    text = " ".join(text.split()).strip(" -")
    # A whole inch drawn left of its fraction is stored after it: «1/4 1» → «1 1/4».
    mixed = re.fullmatch(r"(\d+/\d+) (\d+)", text)
    if mixed:
        text = f"{mixed.group(2)} {mixed.group(1)}"
    return text


def _accessory_rows(page: Any, page_number: int) -> list[dict[str, Any]]:
    """Rows of both tables on one accessories page: right table first."""
    spans = [
        span
        for block in page.get_text("rawdict")["blocks"]
        for line in block.get("lines", [])
        for span in line["spans"]
        if "".join(c["c"] for c in span["chars"]).strip()
    ]

    def text_of(span: dict) -> str:
        return "".join(c["c"] for c in span["chars"])

    headers = {
        key: sorted(
            (s["bbox"] for s in spans if text_of(s).strip().startswith(label)),
            key=lambda bbox: bbox[0],
        )
        for key, label in _ACC_HEADERS.items()
    }
    if any(len(boxes) != 2 for boxes in headers.values()):
        raise SupplierPdfError(
            f"NewPipe accessories page {page_number}: table header not recognized"
        )
    header_bottom = max(box[3] for boxes in headers.values() for box in boxes)
    tables = []
    for side in (0, 1):  # 0 = left table, 1 = right table
        tables.append({
            "left": 0.0 if side == 0 else headers["image"][0][2],
            "carton": headers["carton"][side][0] - 3,
            "box": headers["box"][side][0] - 3,
            "size": headers["box"][side][2] + 2,
            "right": headers["image"][side][0],
        })

    def table_at(x: float) -> int | None:
        for side, table in enumerate(tables):
            if table["left"] <= x < table["right"]:
                return side
        return None

    def mid(bbox) -> tuple[float, float]:
        return (bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2

    # Each product row is anchored on its nine-digit code cell.
    rows: list[dict[str, Any]] = []
    for span in spans:
        x, y = mid(span["bbox"])
        side = table_at(x)
        code = text_of(span).strip()
        if (
            span["color"] == 0 and side is not None and y > header_bottom
            and x > tables[side]["size"] and _ACC_CODE_RE.fullmatch(code)
        ):
            rows.append({"side": side, "y": y, "code": code, "x0": span["bbox"][0],
                         "cells": {"price": "", "carton": "", "box": "", "size": ""}})
    for side, table in enumerate(tables):
        starts = [row["x0"] for row in rows if row["side"] == side]
        table["code"] = (min(starts) if starts else table["right"]) - 3

    headings: list[tuple[int, float, str]] = []
    for span in spans:
        x, y = mid(span["bbox"])
        side = table_at(x)
        if side is None or y <= header_bottom:
            continue
        if span["color"] == _HEADING_RED:
            # «چسب فشار قوی» + «PVC» are two spans on one line.
            if headings and headings[-1][0] == side and abs(headings[-1][1] - y) < 10:
                headings[-1] = (side, headings[-1][1], headings[-1][2] + " " + text_of(span))
            else:
                headings.append((side, y, text_of(span)))
            continue
        if span["color"] != 0:
            continue
        table = tables[side]
        for char in span["chars"]:
            cx, cy = mid(char["bbox"])
            if cx >= table["code"] or cx < table["left"]:
                continue
            column = (
                "price" if cx < table["carton"]
                else "carton" if cx < table["box"]
                else "box" if cx < table["size"]
                else "size"
            )
            near = [r for r in rows if r["side"] == side and abs(r["y"] - cy) <= _ROW_TOLERANCE]
            if near:
                row = min(near, key=lambda r: abs(r["y"] - cy))
                row["cells"][column] += char["c"]

    for row in rows:
        above = [h for h in headings if h[0] == row["side"] and h[1] < row["y"]]
        row["section"] = _acc_text(max(above, key=lambda h: h[1])[2]) if above else None
        row["page"] = page_number
    return sorted(rows, key=lambda r: (-r["side"], r["y"]))


def _persian_words(text: str) -> int:
    return len(re.findall(r"[\u0600-\u06FF]{2,}", text))


class NewPipeProcessor(BaseSupplierProcessor):
    """Processor for لیست قیمت لوله و اتصالات پنج لایه نیوپایپ."""

    supplier_key = SUPPLIER_KEY
    display_name = SUPPLIER_DISPLAY_NAME

    def detection_rules(self) -> DetectionRules:
        # Avoid shared Gitikala footer markers — Dina lists use the same portal.
        return DetectionRules(
            strong_markers=("نیوپایپ", "پیاپوین"),
            weak_markers=("لوله پنج لایه", "اتصالات پنج لایه", "گیتی کالا"),
            websites=(),
            strong_marker_sets=((ACCESSORIES_TITLE, ACCESSORIES_HEADING),),
        )

    def parse_pdf(self, path: str | Path) -> SupplierParseResult:
        source = Path(path)
        if not source.is_file():
            raise SupplierPdfError(f"PDF not found: {source}")

        items: list[SupplierPriceItem] = []
        warnings: list[str] = []
        seen_codes: set[str] = set()
        vat_seen = False
        accessories = False
        page_count = 0
        try:
            probed = pymupdf.open(source)
            try:
                page_count = probed.page_count
                for probe_page in probed:
                    probe_text = probe_page.get_text("text") or ""
                    if "مالیات" in probe_text and "ارزش افزوده" in probe_text:
                        vat_seen = True
                    accessories = accessories or ACCESSORIES_TITLE in probe_text
                if accessories:
                    for page_index, probe_page in enumerate(probed):
                        page_items, page_warnings = self._accessory_items(
                            _accessory_rows(probe_page, page_index + 1),
                            seen_codes=seen_codes,
                            vat_included=vat_seen,
                        )
                        items.extend(page_items)
                        warnings.extend(page_warnings)
            finally:
                probed.close()
            if not accessories:
                with pdfplumber.open(source) as doc:
                    page_count = len(doc.pages)
                    if page_count == 0:
                        raise SupplierPdfError("PDF has no pages")
                    first = doc.pages[0].extract_text() or ""
                    if "نیوپایپ" not in first and "پیاپوین" not in first:
                        warnings.append(
                            "PDF does not clearly identify as نیوپایپ; "
                            "parsing will still be attempted"
                        )
                    for page_index, page in enumerate(doc.pages):
                        tables = page.extract_tables() or []
                        if not tables:
                            warnings.append(f"page {page_index + 1}: no table detected")
                            continue
                        page_items, page_warnings = self._parse_table(
                            tables[0],
                            page_number=page_index + 1,
                            seen_codes=seen_codes,
                            vat_included=vat_seen,
                        )
                        items.extend(page_items)
                        warnings.extend(page_warnings)
        except SupplierPdfError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise SupplierPdfError(f"failed to read NewPipe PDF: {exc}") from exc

        if not items:
            raise SupplierPdfError(
                "No priced products could be extracted from the NewPipe PDF."
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
                "currency": PIONEERS_SALE_CURRENCY,
                "pricing_rule": "direct_replacement_vat_inclusive"
                if vat_seen
                else "direct_replacement_vat_not_seen",
                "vat_note": "PDF states prices include 10% VAT"
                if vat_seen
                else "VAT statement was not found",
            },
        )

    def calculate_final_sale_price(self, item: SupplierPriceItem) -> Decimal:
        # Confirmed: printed Rial. Package length/carton is not multiplied.
        return item.price

    def normalize_supplier_name(self, name: str) -> str:
        return normalize_product_name(name)

    def _accessory_items(
        self,
        rows: list[dict[str, Any]],
        *,
        seen_codes: set[str],
        vat_included: bool,
    ) -> tuple[list[SupplierPriceItem], list[str]]:
        """Accessories rows → items named «نیوپایپ <heading> <size/variant>»."""
        items: list[SupplierPriceItem] = []
        warnings: list[str] = []
        for row in rows:
            code, page, cells = row["code"], row["page"], row["cells"]
            if code in seen_codes:
                warnings.append(f"page {page}: duplicate supplier code {code} skipped")
                continue
            price_raw = cells["price"].strip()
            price = parse_grouped_amount(price_raw)
            if price is None:
                warnings.append(f"page {page}: unreadable price for code {code} ({price_raw!r})")
                continue
            size = _acc_text(cells["size"])
            box = _acc_text(cells["box"])
            # «2 متری», «مایع تیوپی 200cc» describe the product; plain counts do not.
            detail = " ".join(part for part in (size, box if contains_arabic(box) else "") if part)
            section = row["section"]
            parts = [section] if section and section not in detail else []
            parts.append(detail)
            label = " ".join(part for part in parts if part)
            if not label:
                warnings.append(f"page {page}: missing name for code {code}; row skipped")
                continue
            seen_codes.add(code)
            items.append(
                SupplierPriceItem(
                    supplier_id=self.supplier_key,
                    supplier_code=code,
                    supplier_name=f"{SUPPLIER_DISPLAY_NAME} {label}",
                    price=price,
                    unit=None,
                    raw_values={
                        "currency": PIONEERS_SALE_CURRENCY,
                        "original_currency": PIONEERS_SALE_CURRENCY,
                        "original_price": str(price),
                        "original_price_text": price_raw,
                        "price_basis": PRICE_BASIS_PRINTED,
                        "tax": "included_10_percent" if vat_included else "not_stated",
                        "page": page,
                        "column": "right" if row["side"] == 1 else "left",
                        "section": section,
                        "size": size or None,
                        "package_quantity": box or None,
                        "carton_quantity": _acc_text(cells["carton"]) or None,
                        "review_warnings": [],
                        "pricing_blockers": [],
                    },
                )
            )
        return items, warnings

    def _parse_table(
        self,
        table: list[list[Any]],
        *,
        page_number: int,
        seen_codes: set[str],
        vat_included: bool,
    ) -> tuple[list[SupplierPriceItem], list[str]]:
        items: list[SupplierPriceItem] = []
        warnings: list[str] = []
        left_category: str | None = None
        right_category: str | None = None

        for row_index, row in enumerate(table):
            cells = [(c if c is not None else "") for c in (row or [])]
            while len(cells) < 12:
                cells.append("")

            left_code = _cell(cells, _LEFT["code"])
            right_code = _cell(cells, _RIGHT["code"])
            left_is_code = bool(_CODE_RE.fullmatch(left_code))
            right_is_code = bool(_CODE_RE.fullmatch(right_code))

            if not left_is_code:
                label = _category_label(_cell(cells, _LEFT["price"]))
                if label:
                    left_category = label
            if not right_is_code:
                label = _category_label(_cell(cells, _RIGHT["price"]))
                if label:
                    right_category = label

            if left_is_code:
                item, warn = self._row_to_item(
                    code=left_code,
                    price_raw=_cell(cells, _LEFT["price"]),
                    size_raw=_cell(cells, _LEFT["size"]),
                    pack_raw=_cell(cells, _LEFT["pack"]),
                    qty_raw=_cell(cells, _LEFT["qty"]),
                    category=left_category,
                    page_number=page_number,
                    vat_included=vat_included,
                    column="left",
                    row_index=row_index,
                    seen_codes=seen_codes,
                )
                if item:
                    items.append(item)
                if warn:
                    warnings.append(warn)
            if right_is_code:
                item, warn = self._row_to_item(
                    code=right_code,
                    price_raw=_cell(cells, _RIGHT["price"]),
                    size_raw=_cell(cells, _RIGHT["size"]),
                    pack_raw=_cell(cells, _RIGHT["pack"]),
                    qty_raw=_cell(cells, _RIGHT["qty"]),
                    category=right_category,
                    page_number=page_number,
                    vat_included=vat_included,
                    column="right",
                    row_index=row_index,
                    seen_codes=seen_codes,
                )
                if item:
                    items.append(item)
                if warn:
                    warnings.append(warn)
        return items, warnings

    def _row_to_item(
        self,
        *,
        code: str,
        price_raw: str,
        size_raw: str,
        pack_raw: str,
        qty_raw: str,
        category: str | None,
        page_number: int,
        vat_included: bool,
        column: str,
        row_index: int,
        seen_codes: set[str],
    ) -> tuple[SupplierPriceItem | None, str | None]:
        if code in seen_codes:
            return None, f"page {page_number}: duplicate supplier code {code} skipped"
        price = parse_grouped_amount(price_raw)
        if price is None:
            return (
                None,
                f"page {page_number}: unreadable price for code {code} ({price_raw!r})",
            )
        size, size_blocker = _clean_size(size_raw)
        review = [size_blocker] if size_blocker else []
        descriptive = bool(size and _persian_words(size) >= 3)
        if descriptive:
            label = size or ""
        elif category and size:
            label = f"{category} {size}"
        elif category and size_blocker:
            # Keep the row for review with category context; export stays blocked.
            label = category
        elif category:
            label = category
        elif size:
            label = size
        else:
            return (
                None,
                f"page {page_number}: missing name for code {code}; row skipped",
            )

        seen_codes.add(code)
        display = label if label.startswith("نیوپایپ") else f"نیوپایپ {label}"
        display = display.replace('"', " ").replace("(", " ").replace(")", " ")
        display = re.sub(r"\s+", " ", display).strip()
        pack_note = polish_persian(fix_reversed_persian(pack_raw)) if pack_raw else ""
        if pack_note in {"-", "—"}:
            pack_note = ""
        if pack_note and ("رول" in pack_note or "شاخه" in pack_note):
            qty = (qty_raw or "").strip()
            if qty and qty not in {"-", "—", "*"}:
                display = f"{display} {pack_note} {qty}"
            else:
                display = f"{display} {pack_note}"
            display = re.sub(r"\s+", " ", display).strip()
        return (
            SupplierPriceItem(
                supplier_id=self.supplier_key,
                supplier_code=code,
                supplier_name=display,
                price=price,
                unit=None,
                raw_values={
                    "currency": PIONEERS_SALE_CURRENCY,
                    "original_currency": PIONEERS_SALE_CURRENCY,
                    "original_price": str(price),
                    "original_price_text": price_raw,
                    "price_basis": PRICE_BASIS_PRINTED,
                    "tax": "included_10_percent" if vat_included else "not_stated",
                    "page": page_number,
                    "column": column,
                    "table_row": row_index,
                    "section": category,
                    "size": size,
                    "size_raw": size_raw or None,
                    "package_quantity": qty_raw or None,
                    "package_note": pack_note or None,
                    "review_warnings": review,
                    "pricing_blockers": list(review),
                },
            ),
            None,
        )
