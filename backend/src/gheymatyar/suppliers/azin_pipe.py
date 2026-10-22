"""آذین لوله (Azin Pipe) supplier PDF processor.

Based on the real sample ``458_124550609784457.pdf`` — a 5-page Excel-exported
two-column price list titled «لیست قیمت لوله و اتصالات پلی پروپیلن آذین لوله».

Pricing rule (explicit in the PDF footer):
  «قیمت های فوق با احتساب ۱۰٪ مالیات بر ارزش افزوده می باشد»
Prices are used as the final sale price via direct replacement. No extra
markup, tax, or conversion is applied.

Category labels in pdfplumber table cells are character-reversed (LTR dump of
RTL text). Codes, sizes, quantities, and prices are not reversed.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import pdfplumber

from gheymatyar.domain.supplier_item import SupplierPriceItem
from gheymatyar.services.name_normalization import normalize_digits, normalize_product_name
from gheymatyar.suppliers.base import BaseSupplierProcessor, SupplierParseResult
from gheymatyar.suppliers.errors import SupplierPdfError

SUPPLIER_KEY = "azin_pipe"
SUPPLIER_DISPLAY_NAME = "آذین لوله"

_CODE_RE = re.compile(r"^\d{6,}$")
_PRICE_RE = re.compile(r"^[\d,]+$")
_ARABIC_RE = re.compile(r"[\u0600-\u06FF]")

# Headers / noise that must not become category labels.
_SKIP_CATEGORY_FRAGMENTS = (
    "قیمت",
    "اندازه",
    "تصویر",
    "ردیف",
    "متراژ",
    "تعداد",
    "لیست",
    "مالیات",
    "page",
    "لایر(تمیق",  # garbled header remnants
)


def _reverse_token(token: str) -> str:
    """Reverse a mixed Persian/Latin/digit token while keeping numbers intact."""
    parts = re.findall(r"\d+(?:[./]\d+)?|[^\d]+", token)
    transformed: list[str] = []
    for part in parts:
        if part and part[0].isdigit():
            transformed.append(part)
        else:
            transformed.append(part[::-1])
    return "".join(reversed(transformed))


def fix_reversed_persian(text: str) -> str:
    """Repair LTR-reversed Persian labels from pdfplumber table cells."""
    if not text:
        return ""
    text = text.replace("\n", " ").strip()
    if not text or not _ARABIC_RE.search(text):
        return text

    tokens = text.split()
    fixed_tokens = [_reverse_token(t) if _ARABIC_RE.search(t) else t for t in tokens]

    # Latin-leading labels (e.g. "PP RCT - لوله سه لایه") keep Latin prefix.
    if fixed_tokens and not _ARABIC_RE.search(fixed_tokens[0]):
        latin: list[str] = []
        persian: list[str] = []
        for token in fixed_tokens:
            if _ARABIC_RE.search(token) or token in {"-", "–", "—"}:
                persian.append(token)
            else:
                latin.append(token)
        fixed_tokens = list(reversed(persian)) + latin
    else:
        # Pure Persian (or Persian-leading): reverse token order for RTL.
        fixed_tokens = list(reversed(fixed_tokens))

    result = " ".join(fixed_tokens)
    result = normalize_digits(result)
    result = re.sub(r"\s+", " ", result).strip()
    # PDF font often renders «لایه» as «الیه».
    result = result.replace("الیه", "لایه")
    result = result.replace("باال", "بالا")
    result = result.replace("اتصاالت", "اتصالات")
    return result


def _looks_like_category(text: str) -> bool:
    if not text or len(text) < 2:
        return False
    lowered = text.lower()
    if any(frag in lowered for frag in _SKIP_CATEGORY_FRAGMENTS):
        return False
    if _PRICE_RE.match(text.replace(",", "")):
        return False
    if _CODE_RE.match(text):
        return False
    # Require at least one Persian letter for a category label.
    return bool(_ARABIC_RE.search(text))


def _parse_price(raw: str) -> Decimal | None:
    cleaned = normalize_digits(raw).replace(",", "").replace(" ", "").strip()
    if not cleaned or not cleaned.isdigit():
        return None
    try:
        amount = Decimal(cleaned)
    except InvalidOperation:
        return None
    if amount <= 0:
        return None
    return amount


def _clean_size(raw: str | None) -> str | None:
    if not raw:
        return None
    text = normalize_digits(raw.replace("\n", " ")).strip()
    text = text.replace('"', "").replace("'", "").strip()
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"\s*\*\s*", "*", text)
    if not text or text in {"_ _", "_", "-"}:
        return None
    # Size cells may include color words (آبی / قرمز) — keep them.
    text = text.replace("یبآ", "آبی").replace("زمرق", "قرمز")
    return text or None


def _build_display_name(category: str, size: str | None) -> str:
    cat = category.strip()
    # Drop redundant PP-RCT noise for closer Pioneers name alignment.
    cat = re.sub(r"\s*-?\s*PP\s*RCT\s*", " ", cat, flags=re.IGNORECASE)
    cat = re.sub(r"\s+", " ", cat).strip(" -")
    # «لوله های تک لایه» → «لوله تک لایه» to match Pioneers style better.
    cat = cat.replace("لوله های تک لایه", "لوله تک لایه")
    if size:
        return f"اذین {cat} {size}".strip()
    return f"اذین {cat}".strip()


class AzinPipeProcessor(BaseSupplierProcessor):
    """Processor for آذین لوله polypropylene pipe & fitting price lists."""

    supplier_key = SUPPLIER_KEY
    display_name = SUPPLIER_DISPLAY_NAME

    def parse_pdf(self, path: str | Path) -> SupplierParseResult:
        source = Path(path)
        if not source.is_file():
            raise SupplierPdfError(f"PDF not found: {source}")

        warnings: list[str] = []
        items: list[SupplierPriceItem] = []
        seen_codes: set[str] = set()
        page_count = 0

        try:
            with pdfplumber.open(source) as doc:
                page_count = len(doc.pages)
                if page_count == 0:
                    raise SupplierPdfError("PDF has no pages")

                # Sanity-check identity from first page text (PyMuPDF-quality
                # not required — a substring check on extracted text is enough).
                first_text = doc.pages[0].extract_text() or ""
                if "آذین" not in first_text and "اذین" not in first_text:
                    # pdfplumber may reverse characters; check reversed form too.
                    if "نیذآ" not in first_text and "نیدا" not in first_text:
                        warnings.append(
                            "PDF does not clearly identify as آذین لوله; "
                            "parsing will still be attempted"
                        )

                for page_index, page in enumerate(doc.pages):
                    tables = page.extract_tables() or []
                    if not tables:
                        warnings.append(f"page {page_index + 1}: no table detected")
                        continue
                    page_items, page_warnings = self._parse_table(
                        tables[0], page_number=page_index + 1, seen_codes=seen_codes
                    )
                    items.extend(page_items)
                    warnings.extend(page_warnings)
        except SupplierPdfError:
            raise
        except Exception as exc:  # noqa: BLE001 — surface as typed parse error
            raise SupplierPdfError(f"failed to read Azin PDF: {exc}") from exc

        if not items:
            raise SupplierPdfError(
                "No priced products could be extracted from the Azin PDF. "
                "Unsupported or empty price-list structure."
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
                "pricing_rule": "direct_replacement_vat_inclusive",
                "vat_note": "PDF prices already include 10% VAT",
            },
        )

    def calculate_final_sale_price(self, item: SupplierPriceItem) -> Decimal:
        # Confirmed by PDF footer: listed Rial prices include 10% VAT.
        return item.price

    def normalize_supplier_name(self, name: str) -> str:
        return normalize_product_name(name)

    def _parse_table(
        self,
        table: list[list[Any]],
        *,
        page_number: int,
        seen_codes: set[str],
    ) -> tuple[list[SupplierPriceItem], list[str]]:
        items: list[SupplierPriceItem] = []
        warnings: list[str] = []
        left_category: str | None = None
        right_category: str | None = None

        for row_index, row in enumerate(table):
            if not row or len(row) < 10:
                continue
            cells = [(c if c is not None else "") for c in row]
            # Ensure 11 logical columns (pad short rows).
            while len(cells) < 11:
                cells.append("")

            left_price, left_qty, left_size, left_code = cells[0], cells[1], cells[2], cells[3]
            right_price, right_qty, right_size, right_code = (
                cells[6],
                cells[7],
                cells[8],
                cells[9],
            )

            left_has_code = bool(_CODE_RE.match(str(left_code).strip()))
            right_has_code = bool(_CODE_RE.match(str(right_code).strip()))

            if not left_has_code:
                label = fix_reversed_persian(str(left_price))
                if _looks_like_category(label):
                    left_category = label
                # Some category rows put the label only in col0 with PP markers.
                alt = fix_reversed_persian(str(cells[0]))
                if "PP" in str(cells[0]).upper() and _looks_like_category(alt):
                    left_category = alt

            if not right_has_code:
                label = fix_reversed_persian(str(right_price))
                if _looks_like_category(label):
                    right_category = label
                alt = fix_reversed_persian(str(cells[6]))
                if "PP" in str(cells[6]).upper() and _looks_like_category(alt):
                    right_category = alt

            if left_has_code:
                item, warn = self._row_to_item(
                    code=str(left_code).strip(),
                    size_raw=str(left_size) if left_size else None,
                    qty_raw=str(left_qty) if left_qty else None,
                    price_raw=str(left_price),
                    category=left_category,
                    page_number=page_number,
                    column="left",
                    row_index=row_index,
                    seen_codes=seen_codes,
                )
                if item:
                    items.append(item)
                if warn:
                    warnings.append(warn)

            if right_has_code:
                item, warn = self._row_to_item(
                    code=str(right_code).strip(),
                    size_raw=str(right_size) if right_size else None,
                    qty_raw=str(right_qty) if right_qty else None,
                    price_raw=str(right_price),
                    category=right_category,
                    page_number=page_number,
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
        size_raw: str | None,
        qty_raw: str | None,
        price_raw: str,
        category: str | None,
        page_number: int,
        column: str,
        row_index: int,
        seen_codes: set[str],
    ) -> tuple[SupplierPriceItem | None, str | None]:
        if code in seen_codes:
            return None, f"page {page_number}: duplicate supplier code {code} skipped"
        price = _parse_price(price_raw)
        if price is None:
            return (
                None,
                f"page {page_number}: unreadable price for code {code} ({price_raw!r})",
            )
        if not category:
            return (
                None,
                f"page {page_number}: missing category for code {code}; row skipped",
            )

        size = _clean_size(size_raw)
        display_name = _build_display_name(category, size)
        seen_codes.add(code)

        item = SupplierPriceItem(
            supplier_id=self.supplier_key,
            supplier_code=code,
            supplier_name=display_name,
            barcode=None,
            price=price,
            unit=None,
            raw_values={
                "category": category,
                "size": size,
                "quantity_or_meterage": (qty_raw or "").strip() or None,
                "page": page_number,
                "column": column,
                "table_row": row_index,
                "price_raw": price_raw,
                "currency": "rial",
                "price_basis": "listed",
                "tax": "included_10_percent",
            },
        )
        return item, None
