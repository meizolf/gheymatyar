"""نیوپایپ (NewPipe / Gitikala) five-layer pipe price-list processor.

The sample is an 11-page two-column Excel export. pdfplumber keeps each
product's code, size, package counts, and price on one row, while Persian
labels are character-reversed. Package counts (meters in a coil, pieces in
a carton) are not prices and are not multiplied.

The footer states that listed Rial prices already include 10% VAT. Those
amounts are used as printed. No extra tax is added.
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
        )

    def parse_pdf(self, path: str | Path) -> SupplierParseResult:
        source = Path(path)
        if not source.is_file():
            raise SupplierPdfError(f"PDF not found: {source}")

        items: list[SupplierPriceItem] = []
        warnings: list[str] = []
        seen_codes: set[str] = set()
        vat_seen = False
        page_count = 0
        try:
            probed = pymupdf.open(source)
            try:
                page_count = probed.page_count
                for probe_page in probed:
                    probe_text = probe_page.get_text("text") or ""
                    if "مالیات" in probe_text and "ارزش افزوده" in probe_text:
                        vat_seen = True
            finally:
                probed.close()
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
