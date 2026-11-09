"""Sahargas (سحرگاز) steel gas fittings: one page, five side-by-side tables.

pdfplumber reads the page as one grid with three column blocks: concentric
reducers on the left, tees in the middle, and elbows, welded nipples, and
caps stacked on the right. Every block starts at a header row whose «PCS»
cell begins the block and whose «سایز» cell ends it. The cells in between
are price columns, one per construction (مانیسمان, درزدار سنگین, سبک, …),
plus «inch», «DN», and the cap thickness.

One size can have a price per construction; each priced construction is
its own product. Sizes come from the «سایز» code column (2 = 1/2", 10 = 4",
4*2.5 = 1 1/4"×3/4"): it is printed cleanly, while the inch column has
slips such as «3.4» for 3/4. Where a DN column exists it must agree with
the code, or the page is refused.

Prices are Rial as printed: never converted and never multiplied by the
PCS (carton) count. «توافقی», zero, and blank cells are skipped.
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

BRAND = "سحرگاز"
#: The list's size code → (inch, DN).
SIZE_CODES = {
    "2": ("1/2", "15"), "2.5": ("3/4", "20"), "3": ("1", "25"), "4": ("1 1/4", "32"),
    "5": ("1 1/2", "40"), "6": ("2", "50"), "7": ("2 1/2", "65"), "8": ("3", "80"),
    "10": ("4", "100"), "14": ("5", "125"), "16": ("6", "150"), "20": ("8", "200"),
    "25": ("10", "250"), "30": ("12", "300"),
}
#: English word in a table title → (kind, product words).
TABLES = (
    ("reducer", "تبدیل استاندارد"),
    ("tee", "سه راهی"),
    ("elbow", "زانو 90 درجه"),
    ("nipple", "سردنده"),
    ("cap", "کپ استاندارد"),
)
# Title words per table. The tee's English title is interleaved with its
# Persian one in the text layer, so its Persian words are used too.
_TITLE_WORDS = {
    "reducer": ("Reducer",), "tee": ("Tee", "سه راهی"), "elbow": ("Elbow",),
    "nipple": ("Nipple",), "cap": ("Cap",),
}
# English words in the price headers; the Persian words name the construction.
_HEADER_ENGLISH = re.compile(r"\b(?:seamless|seamed|welded|eco)\b|[()]", re.IGNORECASE)


def _text(cell: str | None) -> str:
    lines = [line.strip() for line in (cell or "").split("\n") if line.strip()]
    fixed = [fix_reversed_persian(line) if contains_arabic(line) else line for line in lines]
    return polish_persian(normalize_digits(" ".join(fixed)))


def _compact(cell: str | None) -> str:
    return re.sub(r"\s", "", _text(cell))


def _construction(header: str, sub: str) -> str:
    """«مانیسمان» + «ضخامت رده 40», «درزدار 8 و 10 CM», «سبک», …"""
    words = _HEADER_ENGLISH.sub(" ", _text(header))
    words = re.sub(r"(\d)\s*و\s*(\d)", r"\1 و \2", words)
    label = " ".join(f"{words} {_text(sub)}".split())
    if not label:
        raise SupplierPdfError("Sahargas price column has no construction name")
    return label


class SahargasProcessor(BaseSupplierProcessor):
    supplier_key = "sahargas"
    display_name = "سحرگاز"

    def detection_rules(self) -> DetectionRules:
        return DetectionRules(
            strong_markers=("Sahar Gas", "Sahargas"),
            weak_markers=("Concentric Reducer", "Welded Nipple", "ANSI B16.9"),
            websites=(),
        )

    def parse_pdf(self, path: str | Path) -> SupplierParseResult:
        source = Path(path)
        try:
            with pdfplumber.open(source) as pdf:
                if len(pdf.pages) != 1:
                    raise SupplierPdfError(
                        f"Sahargas list should be one page, found {len(pdf.pages)}"
                    )
                tables = [t.extract() for t in pdf.pages[0].find_tables()]
        except SupplierPdfError:
            raise
        except Exception as exc:  # noqa: BLE001 - pdfplumber failures
            raise SupplierPdfError(f"could not read Sahargas PDF: {exc}") from exc
        grid = max(tables, key=lambda t: len(t[0]) if t else 0, default=None)
        if not grid:
            raise SupplierPdfError("Sahargas list has no price table")
        items: list[SupplierPriceItem] = []
        skipped: list[str] = []
        for header_row, start, end in self._blocks(grid):
            items.extend(self._read_block(grid, header_row, start, end, skipped))
        names = [item.supplier_name for item in items]
        if not items:
            raise SupplierPdfError("Sahargas list has no priced products")
        if len(names) != len(set(names)):
            repeated = sorted({n for n in names if names.count(n) > 1})
            raise SupplierPdfError(f"Sahargas list repeats product names: {repeated[:3]}")
        kinds = {item.raw_values["table"] for item in items}
        if kinds != {kind for kind, _words in TABLES}:
            raise SupplierPdfError(f"Sahargas tables found: {sorted(kinds)}; expected all five")
        warnings = [f"skipped {len(skipped)} cells without a price"] if skipped else []
        return SupplierParseResult(
            supplier_key=self.supplier_key,
            supplier_display_name=self.display_name,
            items=items,
            warnings=warnings + skipped[:20],
            source_metadata={"source": "pdf", "file": source.name, "item_count": len(items)},
        )

    @staticmethod
    def _blocks(grid: list[list[str | None]]) -> list[tuple[int, int, int]]:
        """(header row, «PCS» column, «سایز» column) for every table."""
        blocks = []
        for row_index, row in enumerate(grid):
            for col, cell in enumerate(row):
                if "PCS" not in (cell or ""):
                    continue
                end = next(
                    (c for c in range(col + 1, len(row)) if _compact(row[c]) == "سایز"), None
                )
                if end is None:
                    raise SupplierPdfError(f"Sahargas table at row {row_index + 1} has no size column")
                blocks.append((row_index, col, end))
        return blocks

    def _read_block(self, grid, header_row: int, start: int, end: int, skipped: list[str]):
        title = next(
            (grid[r][start] for r in range(header_row - 1, -1, -1) if (grid[r][start] or "").strip()),
            "",
        )
        title_text = f"{title} {_text(title)}"
        kind = next(
            (k for k, keys in _TITLE_WORDS.items() if any(key in title_text for key in keys)),
            None,
        )
        if kind is None:
            raise SupplierPdfError(f"Sahargas table title not recognized: {title!r}")
        words = dict(TABLES)[kind]
        header = grid[header_row]
        columns = {_compact(header[c]): c for c in range(start + 1, end)}
        inch_col = columns.get("inch")
        dn_col = columns.get("DN")
        thickness_col = columns.get("ضخامت")
        price_cols = [
            c for c in range(start + 1, end)
            if c not in {inch_col, dn_col, thickness_col} and (header[c] or "").strip()
        ]
        if not price_cols:
            raise SupplierPdfError(f"Sahargas {kind} table has no price columns")
        # A sub-header such as «ضخامت رده 40» completes the column name.
        sub_row = grid[header_row + 1] if header_row + 1 < len(grid) else []
        has_sub = not (sub_row[end] or "").strip() and any(
            (sub_row[c] or "").strip() for c in price_cols
        )
        constructions = {
            c: _construction(header[c], sub_row[c] if has_sub else "") for c in price_cols
        }
        items: list[SupplierPriceItem] = []
        for row_index in range(header_row + (2 if has_sub else 1), len(grid)):
            row = grid[row_index]
            if "PCS" in (row[start] or "") or (
                not _compact(row[end]) and (row[start] or "").strip()
            ):
                break  # the next table of this block (its title row)
            code = _compact(row[end])
            if not code:
                continue
            for col in price_cols:
                raw = (row[col] or "").strip()
                amount = parse_grouped_amount(raw)
                if amount is None:
                    if raw:
                        skipped.append(f"{kind} {code} {constructions[col]}: {_text(raw)!r}")
                    continue
                sizes = self._sizes(code, row[dn_col] if dn_col is not None else None, kind)
                if sizes is None:
                    skipped.append(f"{kind} {code}: size code not readable")
                    continue
                items.append(self._item(kind, words, sizes, constructions[col], amount,
                                        thickness=(
                                            _text(row[thickness_col])
                                            if thickness_col is not None else None
                                        ),
                                        row=row_index + 1, code=code, pcs=_text(row[start])))
        return items

    @staticmethod
    def _sizes(code: str, dn: str | None, kind: str) -> list[str] | None:
        parts = code.split("*")
        if not all(part in SIZE_CODES for part in parts) or len(parts) > 2:
            return None
        if dn is not None and len(parts) == 1 and _compact(dn) != SIZE_CODES[parts[0]][1]:
            raise SupplierPdfError(
                f"Sahargas {kind} size {code} has DN {_compact(dn)}, expected "
                f"{SIZE_CODES[parts[0]][1]}: columns are misaligned"
            )
        return [SIZE_CODES[part][0] for part in parts]

    def _item(self, kind: str, words: str, sizes: list[str], construction: str,
              amount: Decimal, *, thickness: str | None, row: int, code: str,
              pcs: str) -> SupplierPriceItem:
        if kind == "tee":
            words = f"{words} {'تبدیلی' if len(sizes) == 2 else 'مساوی'}"
        detail = construction
        if thickness:
            # «میل 2.5» as printed → «ضخامت 2.5 میل».
            mm = re.search(r"\d+(?:\.\d+)?", thickness)
            if mm is None:
                raise SupplierPdfError(f"Sahargas cap thickness not readable: {thickness!r}")
            detail = f"{construction} ضخامت {mm.group(0)} میل"
        name = f"{words} {BRAND} {'×'.join(sizes)} اینچ {detail}"
        return SupplierPriceItem(
            supplier_id=self.supplier_key,
            supplier_name=name,
            price=amount,
            raw_values={
                "currency": PIONEERS_SALE_CURRENCY,
                "price_basis": "printed",
                "tax": "not_stated",
                "page": 1,
                "table": kind,
                "size_code": code,
                "dn": SIZE_CODES[code][1] if code in SIZE_CODES else None,
                "construction": construction,
                "package_count": pcs or None,
                "table_row": row,
            },
        )
