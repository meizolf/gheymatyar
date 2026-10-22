"""لوله آبراهان (Abrahan Pipe) cash price-list processor.

Two pages, each split into a left and a right table. Section headings
(لوله، زانو، بوشن، …) apply to the following rows. The price column is
Rial. متراژ/تعداد is the package quantity and is not multiplied.

Rows marked موجود have no price and are reported as warnings.
The sheet is titled لیست قیمت نقدی and does not state a VAT rule.
"""

from __future__ import annotations

import re
from decimal import Decimal
from pathlib import Path

import pymupdf

from gheymatyar.domain.supplier_item import SupplierPriceItem
from gheymatyar.services.name_normalization import normalize_digits, normalize_product_name
from gheymatyar.suppliers.base import BaseSupplierProcessor, SupplierParseResult
from gheymatyar.suppliers.errors import SupplierPdfError
from gheymatyar.suppliers.textutil import contains_arabic, parse_grouped_amount, polish_persian

SUPPLIER_KEY = "abrahan_pipe"
SUPPLIER_DISPLAY_NAME = "لوله آبراهان"

_PRICE_RE = re.compile(r"^\d{1,3}(?:,\d{3})+$")
_ROW_RE = re.compile(r"^\d{1,3}$")
_FRACTIONS = {"½": "1/2", "¼": "1/4", "¾": "3/4"}


def _lines(words: list[tuple]) -> list[list[tuple]]:
    lines: list[list[tuple]] = []
    for word in sorted(words, key=lambda item: (item[1], item[0])):
        # Wrapped size text sits about 3pt above its price. Distinct rows are ~9pt apart.
        if lines and abs(word[1] - lines[-1][0][1]) <= 4.2:
            lines[-1].append(word)
        else:
            lines.append([word])
    return lines


def _reading(words: list[tuple]) -> str:
    parts = []
    for word in sorted(words, key=lambda item: -item[0]):
        text = normalize_digits(word[4])
        for src, dst in _FRACTIONS.items():
            text = text.replace(src, dst)
        parts.append(text)
    return polish_persian(" ".join(parts))


def _header_centers(words: list[tuple]) -> dict[str, float] | None:
    centers: dict[str, float] = {}
    for word in words:
        token = word[4]
        center = (word[0] + word[2]) / 2
        if token == "ردیف":
            centers["row"] = center
        elif token == "سایز":
            centers["size"] = center
        elif "قیمت" in token:
            centers["price"] = center
        elif token in {"تعداد", "متراژ"} or "متراژ" in token:
            centers["qty"] = center
    if "price" in centers and "size" in centers:
        return centers
    return None


def _nearest(center: float, columns: dict[str, float]) -> str | None:
    name = min(columns, key=lambda key: abs(columns[key] - center))
    if abs(columns[name] - center) <= 42:
        return name
    return None


def _column_text(words: list[tuple], column: str, columns: dict[str, float]) -> str:
    chosen = []
    for word in words:
        center = (word[0] + word[2]) / 2
        if _nearest(center, columns) == column:
            chosen.append(word)
    if not chosen:
        return ""
    return _reading(chosen)


class AbrahanPipeProcessor(BaseSupplierProcessor):
    """Processor for لیست قیمت نقدی محصولات لوله آبراهان."""

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
            doc = pymupdf.open(source)
        except Exception as exc:  # noqa: BLE001
            raise SupplierPdfError(f"failed to read Abrahan PDF: {exc}") from exc
        try:
            page_count = doc.page_count
            if page_count == 0:
                raise SupplierPdfError("PDF has no pages")
            first = doc[0].get_text("text") or ""
            if "آبراهان" not in first and "ابراهان" not in first and "ABRAHAN" not in first.upper():
                warnings.append(
                    "PDF does not clearly identify as لوله آبراهان; "
                    "parsing will still be attempted"
                )
            for page_index, page in enumerate(doc):
                page_items, page_warnings = self._parse_page(page, page_number=page_index + 1)
                items.extend(page_items)
                warnings.extend(page_warnings)
        finally:
            doc.close()

        if not items:
            raise SupplierPdfError(
                "No priced products could be extracted from the Abrahan PDF."
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
                "currency": "rial",
                "pricing_rule": "printed_cash_rial",
                "vat_note": "PDF does not state whether VAT is included",
            },
        )

    def calculate_final_sale_price(self, item: SupplierPriceItem) -> Decimal:
        return item.price

    def normalize_supplier_name(self, name: str) -> str:
        return normalize_product_name(name)

    def _parse_page(
        self, page: pymupdf.Page, *, page_number: int
    ) -> tuple[list[SupplierPriceItem], list[str]]:
        words = page.get_text("words")
        midpoint = page.rect.width / 2
        items: list[SupplierPriceItem] = []
        warnings: list[str] = []
        for side, selected in (
            ("right", [word for word in words if word[0] >= midpoint - 8]),
            ("left", [word for word in words if word[0] < midpoint - 8]),
        ):
            side_items, side_warnings = self._parse_side(
                selected, page_number=page_number, side=side
            )
            items.extend(side_items)
            warnings.extend(side_warnings)
        return items, warnings

    def _parse_side(
        self,
        words: list[tuple],
        *,
        page_number: int,
        side: str,
    ) -> tuple[list[SupplierPriceItem], list[str]]:
        items: list[SupplierPriceItem] = []
        warnings: list[str] = []
        columns: dict[str, float] | None = None
        category: str | None = None

        for line in _lines(words):
            header = _header_centers(line)
            if header:
                columns = header
                continue
            if columns is None:
                continue
            blob = _reading(line)
            if not blob or "ABRAHAN" in blob.upper() or "لیست قیمت" in blob:
                continue
            price_text = _column_text(line, "price", columns)
            if "موجود" in price_text or "موجود" in blob:
                warnings.append(
                    f"page {page_number} {side}: unavailable row skipped ({blob})"
                )
                continue
            price = parse_grouped_amount(price_text)
            if price is None:
                # A heading such as «زانو 45 درجه» has no grouped price.
                if contains_arabic(blob) and not _PRICE_RE.search(blob):
                    if not _ROW_RE.fullmatch(blob) and "قیمت" not in blob and "ردیف" not in blob:
                        category = blob
                continue

            size = _column_text(line, "size", columns)
            qty = _column_text(line, "qty", columns)
            row_no = _column_text(line, "row", columns)
            size = size.replace(" ", "") if re.fullmatch(r"[\d\s\-/]+", size or "") else size
            if not category:
                warnings.append(
                    f"page {page_number} {side}: missing section for size {size or '?'}; row skipped"
                )
                continue
            # Reject a quantity or row number that landed in the price column.
            if row_no and str(price) == row_no:
                continue
            name = f"آبراهان {category}"
            if size:
                name = f"{name} {size}"
            name = re.sub(r"\s+", " ", name).strip()
            items.append(
                SupplierPriceItem(
                    supplier_id=self.supplier_key,
                    supplier_code=None,
                    supplier_name=name,
                    price=price,
                    unit=None,
                    raw_values={
                        "currency": "rial",
                        "original_price": str(price),
                        "original_price_text": price_text,
                        "price_basis": "listed",
                        "tax": "not_stated",
                        "page": page_number,
                        "column": side,
                        "section": category,
                        "size": size or None,
                        "package_quantity": qty or None,
                        "source_row_number": row_no or None,
                        "review_warnings": [],
                    },
                )
            )
        return items, warnings
