"""Galvanized fitting price matrices: «اتصالات ایرانی» and «زاکو و خارجی».

Both lists are one-page Excel exports. Product types are rows and inch sizes
are columns (4" on the left down to 1/2" on the right). Every non-empty
product/size cell is one product. Prices are cash Rial: never converted,
never multiplied by a pack count, and never discounted or taxed. A cell that
is not a grouped Rial amount is skipped and reported, never guessed.

Row labels can carry their own size. In «تبدیل "1 1/4"» under the 1"
column, the product is a 1 1/4"×1" reducer. Reducer pairs are written larger
size first, so the name does not depend on how the PDF ordered them.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Iterable

import pdfplumber

from gheymatyar.domain.sale_policy import PIONEERS_SALE_CURRENCY
from gheymatyar.domain.supplier_item import SupplierPriceItem
from gheymatyar.suppliers.azin_pipe import fix_reversed_persian
from gheymatyar.suppliers.base import BaseSupplierProcessor, SupplierParseResult
from gheymatyar.suppliers.detection import DetectionRules
from gheymatyar.suppliers.errors import SupplierPdfError
from gheymatyar.suppliers.fitting_sizes import inch_part, size_text, split_label
from gheymatyar.suppliers.textutil import contains_arabic, parse_grouped_amount, polish_persian

#: Size columns, left to right, as printed in both lists.
SIZE_COLUMNS = ("4", "3", "2 1/2", "2", "1 1/2", "1 1/4", "1", "3/4", "1/2")
# Spelling slips and glyph artifacts seen in these two lists.
_LABEL_FIXES = (("تیدیل", "تبدیل"), ("طالیی", "طلایی"), ("طلایی ", "طلایی "))


def _cell_text(cell: str | None) -> str:
    raw = (cell or "").replace("\n", " ").strip()
    if contains_arabic(raw):
        raw = fix_reversed_persian(raw)
    text = polish_persian(raw)
    for wrong, right in _LABEL_FIXES:
        text = text.replace(wrong, right)
    return text


def _inch_value(size: str) -> Decimal:
    total = Decimal(0)
    for part in size.split():
        if "/" in part:
            num, den = part.split("/")
            total += Decimal(num) / Decimal(den)
        else:
            total += Decimal(part)
    return total


def _header_sizes(row: Iterable[str | None]) -> list[str | None]:
    return [inch_part((cell or "").replace("\n", " ")) for cell in row]


def product_name(prefix: str, label: str, column_size: str | None) -> str | None:
    """One full name: list prefix, product, and size (row × column for reducers)."""
    words, label_sizes = split_label(label)
    if not words:
        return None
    sizes = list(label_sizes)
    if column_size is not None:
        sizes.append(column_size)
    if len(sizes) == 2:
        sizes.sort(key=_inch_value, reverse=True)
    if len(set(sizes)) != len(sizes):
        return None  # a reducer to its own size is not a real product
    tail = f" سایز {size_text(sizes)}" if sizes else ""
    return f"{prefix} {words}{tail}"


def _item(supplier_key: str, name: str, amount: Decimal, *, label: str,
          column: str | None, row: int, section: str | None = None) -> SupplierPriceItem:
    return SupplierPriceItem(
        supplier_id=supplier_key,
        supplier_name=name,
        price=amount,
        raw_values={
            "currency": PIONEERS_SALE_CURRENCY,
            "price_basis": "printed",
            "tax": "not_stated",
            "page": 1,
            "row_label": label,
            "size_column": column,
            "table_row": row,
            **({"section": section} if section else {}),
        },
    )


class _MatrixProcessor(BaseSupplierProcessor):
    """Shared reading of a one-page product × inch-size price matrix."""

    #: Name prefix for every product of this list.
    name_prefix: str
    #: Text that must appear in the list title or header (identity check).
    title_marker: str

    def parse_pdf(self, path: str | Path) -> SupplierParseResult:
        source = Path(path)
        try:
            with pdfplumber.open(source) as pdf:
                if len(pdf.pages) != 1:
                    raise SupplierPdfError(
                        f"{self.display_name} list should be one page, found {len(pdf.pages)}"
                    )
                tables = pdf.pages[0].extract_tables() or []
        except SupplierPdfError:
            raise
        except Exception as exc:  # noqa: BLE001 - pdfplumber failures
            raise SupplierPdfError(f"could not read {self.display_name} PDF: {exc}") from exc
        if len(tables) != 1:
            raise SupplierPdfError(
                f"{self.display_name} list should have one price table, found {len(tables)}"
            )
        items, warnings = self._read_table(tables[0])
        names = [item.supplier_name for item in items]
        if not items:
            raise SupplierPdfError(f"{self.display_name} list has no priced products")
        if len(names) != len(set(names)):
            repeated = sorted({n for n in names if names.count(n) > 1})
            raise SupplierPdfError(
                f"{self.display_name} list repeats product names: {repeated[:3]}"
            )
        return SupplierParseResult(
            supplier_key=self.supplier_key,
            supplier_display_name=self.display_name,
            items=items,
            warnings=warnings,
            source_metadata={"source": "pdf", "file": source.name, "item_count": len(items)},
        )

    def _header_row_index(self, table: list[list[str | None]]) -> int:
        for index, row in enumerate(table[:3]):
            if _header_sizes(row[: len(SIZE_COLUMNS)]) == list(SIZE_COLUMNS):
                return index
        raise SupplierPdfError(
            f"{self.display_name} size columns are not {', '.join(SIZE_COLUMNS)}"
        )

    def _read_table(
        self, table: list[list[str | None]]
    ) -> tuple[list[SupplierPriceItem], list[str]]:
        header = self._header_row_index(table)
        heading = " ".join(_cell_text(c) for row in table[: header + 1] for c in row if c)
        if self.title_marker not in heading:
            raise SupplierPdfError(f"price table is not the {self.display_name} list")
        items: list[SupplierPriceItem] = []
        skipped: list[str] = []
        section: str | None = None
        for row_index, row in enumerate(table[header + 1 :], start=header + 2):
            cells = list(row) + [None] * (len(SIZE_COLUMNS) + 1 - len(row))
            label = _cell_text(cells[len(SIZE_COLUMNS)])
            prices = cells[: len(SIZE_COLUMNS)]
            texts = [_cell_text(c) for c in prices]
            if not label and texts[0] and not any(texts[1:]):
                section = texts[0]  # a full-width divider such as «اتصالات سیاه»
                continue
            mixed = [i for i, text in enumerate(texts) if text and contains_arabic(text)]
            if mixed:
                pairs = [(len(SIZE_COLUMNS), len(SIZE_COLUMNS) - 1), *[(i, i - 1) for i in mixed]]
                for label_at, price_at in pairs:
                    text = label if label_at == len(SIZE_COLUMNS) else texts[label_at]
                    raw = cells[price_at] if price_at >= 0 else None
                    self._add(items, skipped, text, None, raw, row_index, section)
                continue
            if not label:
                if any(texts):
                    skipped.append(f"row {row_index}: prices without a product label")
                continue
            for column, raw in zip(SIZE_COLUMNS, prices):
                self._add(items, skipped, label, column, raw, row_index, section)
        warnings = [f"skipped {len(skipped)} cells that are not a clear price"] if skipped else []
        return items, warnings + skipped[:20]

    def _add(self, items, skipped, label, column, raw, row_index, section) -> None:
        text = (raw or "").strip()
        if not text:
            return
        amount = parse_grouped_amount(text)
        if amount is None:
            skipped.append(f"row {row_index} «{label}» {column or ''}: {text!r}")
            return
        name = product_name(self.name_prefix, label, column)
        if name is None:
            skipped.append(f"row {row_index} «{label}» {column or ''}: no clear product size")
            return
        items.append(
            _item(self.supplier_key, name, amount, label=label, column=column,
                  row=row_index, section=section)
        )


class IranianFittingsProcessor(_MatrixProcessor):
    """«لیست قیمت نقدی انواع اتصالات ایرانی آبکاری سرد» (one-page matrix)."""

    supplier_key = "iranian_fittings"
    display_name = "اتصالات ایرانی"
    name_prefix = "اتصالات ایرانی آبکاری سرد"
    title_marker = "اتصالات ایرانی آبکاری سرد"

    def detection_rules(self) -> DetectionRules:
        return DetectionRules(
            strong_markers=("iranetesalat",),
            weak_markers=("آبکاری سرد", "ایرانی"),
            websites=("iranetesalat.com",),
        )


class ZacoForeignFittingsProcessor(_MatrixProcessor):
    """«لیست قیمت موقت نقدی اتصالات — زاکو و خارجی» (one-page matrix).

    The list covers Zaco and foreign fittings without marking each row, so
    every name carries the list's own «زاکو و خارجی» rather than a guessed
    brand. Row words such as «زاکو» or «سیاه» stay in the name, and rows
    under the «اتصالات سیاه» divider are black fittings.
    """

    supplier_key = "zaco_foreign_fittings"
    display_name = "اتصالات زاکو و خارجی"
    name_prefix = "اتصالات زاکو و خارجی"
    title_marker = "www.zaco.co"

    def detection_rules(self) -> DetectionRules:
        return DetectionRules(
            strong_markers=("zaco.co",),
            weak_markers=("زاکو", "خارجی", "سیاه"),
            websites=("zaco.co",),
        )

    def _read_table(self, table):
        items, warnings = super()._read_table(table)
        fixed: list[SupplierPriceItem] = []
        for item in items:
            # Rows under «اتصالات سیاه» are black even if the label omits it.
            if item.raw_values.get("section") and "سیاه" not in item.supplier_name:
                words = item.supplier_name.split(" سایز ")
                name = f"{words[0]} سیاه" + (f" سایز {words[1]}" if len(words) > 1 else "")
                item = item.model_copy(update={"supplier_name": name})
            fixed.append(item)
        return fixed, warnings
