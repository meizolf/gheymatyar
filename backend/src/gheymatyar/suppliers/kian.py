"""گروه تولیدی صنعتی کیان (Kian Industrial Group) hose price-list processor.

The sample is a 5-page Mehr 1405 list. Pages 1–4 are priced tables; page 5
is packaging quantities and a variable discount note. Those notes are not
applied.

Confirmed rule: printed prices are Toman. Pioneers ``نرخ فروش اصلی`` is Rial,
so ``calculate_final_sale_price`` multiplies by 10 with ``Decimal`` exactly
once. Carton quantities and the bulk-order discount are not part of the price.

A row may carry up to three materials (اکونومی، آلومینیوم، استیل) or two
grades (A و B). Each priced code becomes its own product. A price cell is
missing only when every nonblank token is a dash; that variant is not
invented. A dash or minus sign next to an amount is a blocked cell, not a
positive price. A cell is accepted only when its tokens are one amount,
including an unambiguous decimal. Leftover text blocks export. The product
name is one Persian string: brand, type, connection, size, material or grade,
the page-5 construction notes those labels refer to, and color.
"""

from __future__ import annotations

import re
from decimal import Decimal
from pathlib import Path
from typing import Callable, NamedTuple

import pymupdf

from gheymatyar.domain.sale_policy import (
    PIONEERS_SALE_CURRENCY,
    PRICE_BASIS_PRINTED,
    TOMAN_TO_RIAL,
)
from gheymatyar.domain.supplier_item import SupplierPriceItem
from gheymatyar.services.name_normalization import normalize_digits, normalize_product_name
from gheymatyar.suppliers.base import BaseSupplierProcessor, SupplierParseResult
from gheymatyar.suppliers.detection import DetectionRules
from gheymatyar.suppliers.errors import SupplierPdfError
from gheymatyar.suppliers.textutil import parse_grouped_amount, polish_persian

SUPPLIER_KEY = "kian"
SUPPLIER_DISPLAY_NAME = "گروه تولیدی صنعتی کیان"

_CODE_RE = re.compile(r"^\d{3,4}$")
_NUMBER_RE = re.compile(r"^\d{2,3}$")
_PAREN_LINE_RE = re.compile(r"^\([^)]*\)$")
# Hyphen, figure dash, en dash, em dash, and the Unicode minus sign.
_DASH_RE = re.compile(r"^[-‒–—−]+$")
_FRACTION_TOKEN_RE = re.compile(r"^\.\d+$")
_COMMA_DECIMAL_RE = re.compile(r"^(\d{1,3}(?:,\d{3})+)\.(\d+)$")
_PRICE_CELL_BLOCKER = "price cell is not a single amount; automatic export is blocked"

# Page 5 states these characteristics. They belong in the name, not in the price.
_MATERIAL_SPEC = {
    "اکونومی": "بافت آلومینیوم دنباله برنجی اتصالات استیل بدون لیبل و کارتن",
    "آلومینیوم": "بافت آلومینیوم قطعات برنجی با لیبل و کارتن",
    "استیل": "بافت استیل قطعات برنجی با لیبل و کارتن",
}
# The text layer writes قلاب as قالب and نری as نرک, the same glyph mix-up as طلا/طال.
_GRADE_SPEC = {
    "A": "تمامی قطعات برنجی زره کروم دوسربوش بلند دسته آسان شور قلاب گرد",
    "B": "کونیک زینک زره پولیش مهره استیل نری برنجی دوسربوش کوتاه قلاب ساده",
}
_LINE_Y_TOLERANCE = 7.0
_BLOCK_GAP = 4.0

# Product nouns. Connection words such as دوسر مهره are qualifiers, not heads.
_PRIMARY_NOUNS = (
    "آبگرمکن",
    "پکیجی",
    "پیسواری",
    "تکپایه",
    "رابط",
    "تست",
    "توالت",
    "دوش",
    "یکسرمهره",
    "یکسر مهره",
)
_HEAD_ORDER = (
    "آبگرمکن",
    "پکیجی",
    "پیسواری",
    "تکپایه",
    "رابط",
    "تست",
    "توالت",
    "دوش",
    "یکسر",
    "دوسر",
)

_AnchorPred = Callable[[str], bool]
_ANCHORS: dict[str, tuple[tuple[str, _AnchorPred], ...]] = {
    "triple": (
        ("steel_price", lambda text: text == "استیل"),
        ("steel_code", lambda text: text == "کد"),
        ("alu_price", lambda text: "آلومینیوم" in text),
        ("alu_code", lambda text: text == "کد"),
        ("eco_price", lambda text: "اکونومی" in text),
        ("eco_code", lambda text: text == "کد"),
        ("size", lambda text: text == "اندازه"),
        ("description", lambda text: text == "شرح"),
    ),
    "steel": (
        ("steel_price", lambda text: text == "استیل"),
        ("steel_code", lambda text: text == "کد"),
        ("size", lambda text: text == "اندازه"),
        ("description", lambda text: text == "شرح"),
    ),
    "grade": (
        ("grade_a_price", lambda text: text == "گرید"),
        ("grade_a_code", lambda text: text == "کد"),
        ("grade_b_price", lambda text: text == "گرید"),
        ("grade_b_code", lambda text: text == "کد"),
        ("description", lambda text: text == "شرح"),
        ("color", lambda text: text == "رنگ"),
    ),
    "single": (
        ("price", lambda text: text == "قیمت"),
        ("code", lambda text: text == "کد"),
        ("color", lambda text: text == "رنگ"),
        ("description", lambda text: text == "شرح"),
    ),
}

_VARIANTS: dict[str, tuple[tuple[str, str, str | None, str | None], ...]] = {
    # price role, code role, material, grade — right-hand column first.
    "triple": (
        ("eco_price", "eco_code", "اکونومی", None),
        ("alu_price", "alu_code", "آلومینیوم", None),
        ("steel_price", "steel_code", "استیل", None),
    ),
    "steel": (("steel_price", "steel_code", "استیل", None),),
    "grade": (
        ("grade_b_price", "grade_b_code", None, "B"),
        ("grade_a_price", "grade_a_code", None, "A"),
    ),
    "single": (("price", "code", None, None),),
}


def _yc(word: tuple) -> float:
    return (word[1] + word[3]) / 2.0


def _xc(word: tuple) -> float:
    return (word[0] + word[2]) / 2.0


def _polish_fragment(text: str) -> str:
    cleaned = polish_persian(text)
    cleaned = cleaned.replace("یکسرمهره", "یکسر مهره")
    cleaned = re.sub(r"(?<![\u0600-\u06FF])طال(?![\u0600-\u06FF])", "طلا", cleaned)
    cleaned = re.sub(r"\(\s+", "(", cleaned)
    cleaned = re.sub(r"\s+\)", ")", cleaned)
    cleaned = re.sub(r"\s*\*\s*", " * ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def _has_primary(text: str) -> bool:
    return any(noun in text for noun in _PRIMARY_NOUNS)


def _cluster_lines(words: list[tuple]) -> list[str]:
    if not words:
        return []
    ordered = sorted(words, key=lambda word: (_yc(word), -_xc(word)))
    lines: list[list[tuple]] = []
    for word in ordered:
        if lines and abs(_yc(word) - _yc(lines[-1][0])) <= _LINE_Y_TOLERANCE:
            lines[-1].append(word)
        else:
            lines.append([word])
    texts: list[str] = []
    for line in lines:
        tokens = [word[4] for word in sorted(line, key=lambda word: -_xc(word))]
        text = _polish_fragment(" ".join(tokens))
        if text:
            texts.append(text)
    return texts


def _compose_description(lines: list[str]) -> str:
    """Put the product noun first and parenthetical qualifiers last."""
    if not lines:
        return ""
    parens = [line for line in lines if _PAREN_LINE_RE.match(line)]
    body = [line for line in lines if line not in parens]
    if not body:
        return _polish_fragment(" ".join(parens))

    def rank(line: str) -> int:
        for index, marker in enumerate(_HEAD_ORDER):
            if marker in line:
                return index
        return len(_HEAD_ORDER)

    best = min(range(len(body)), key=lambda index: (rank(body[index]), index))
    ordered = [body[best], *[line for index, line in enumerate(body) if index != best]]
    return _polish_fragment(" ".join([*ordered, *parens]))


def _length_text(words: list[tuple]) -> str | None:
    number: str | None = None
    unit = False
    for word in words:
        token = normalize_digits(word[4])
        if token in {"سانت", "سانتی", "سانتیمتر"}:
            unit = True
        elif _NUMBER_RE.fullmatch(token):
            number = token
    if number and unit:
        return f"{number} سانت"
    return None


class _PriceCell(NamedTuple):
    kind: str
    text: str
    amount: Decimal | None
    blocker: str | None


def _amount_token(token: str) -> str:
    return (
        normalize_digits(token)
        .replace(" ", "")
        .replace("\u066c", ",")
        .replace("\u060c", ",")
        .replace("٬", ",")
        .replace("٫", ".")
        .strip()
    )


def _parse_amount_text(token: str) -> Decimal | None:
    """Parse one complete amount. Grouped integers stay integers.

    A comma is a thousands separator. A dot is a decimal point only when the
    cell is not a thousands-grouped integer such as ``260.800``. Mixed
    ``260,800.5`` is one Decimal. Anything else, including leftover text, is
    not an amount.
    """
    compact = _amount_token(token)
    if not compact or _DASH_RE.fullmatch(compact):
        return None
    if not re.fullmatch(r"[\d.,]+", compact):
        return None
    grouped = parse_grouped_amount(compact)
    if grouped is not None:
        return grouped
    mixed = _COMMA_DECIMAL_RE.fullmatch(compact)
    if mixed:
        amount = Decimal(mixed.group(1).replace(",", "") + "." + mixed.group(2))
        return amount if amount > 0 else None
    if re.fullmatch(r"\d+\.\d+", compact) and not re.fullmatch(
        r"\d{1,3}(?:\.\d{3})+", compact
    ):
        amount = Decimal(compact)
        return amount if amount > 0 else None
    if re.fullmatch(r"\d+", compact):
        amount = Decimal(compact)
        return amount if amount > 0 else None
    return None


def _read_price_cell(words: list[tuple]) -> _PriceCell:
    """Accept a cell only when its tokens are exactly one amount.

    ``260,800`` plus ``.5`` is ``260800.5``. ``260,800`` plus ``#N/A``, or a
    dash or minus sign beside an amount, is blocked. The diagnostic text keeps
    every token. A cell is missing only when every nonblank token is a dash.
    """
    ordered = [
        word[4].strip()
        for word in sorted(words, key=lambda item: (item[0], item[1]))
        if word[4].strip()
    ]
    if not ordered:
        return _PriceCell("absent", "", None, None)
    text = " ".join(ordered)
    if all(_DASH_RE.fullmatch(token) for token in ordered):
        return _PriceCell("dashed", text, None, None)
    amount = _accepted_cell_amount(ordered)
    if amount is not None:
        return _PriceCell("ok", text, amount, None)
    partials = [
        parsed
        for token in ordered
        if (parsed := _parse_amount_text(token)) is not None
    ]
    if len(partials) == 1:
        return _PriceCell("blocked", text, partials[0], f"{_PRICE_CELL_BLOCKER}: {text}")
    return _PriceCell("unreadable", text, None, None)


def _accepted_cell_amount(tokens: list[str]) -> Decimal | None:
    if len(tokens) == 1:
        return _parse_amount_text(tokens[0])
    if len(tokens) == 2 and _FRACTION_TOKEN_RE.fullmatch(_amount_token(tokens[1])):
        return _parse_amount_text(tokens[0] + tokens[1])
    return None


def _codes(words: list[tuple]) -> list[str]:
    found: list[str] = []
    for word in words:
        token = normalize_digits(word[4].strip())
        if _CODE_RE.fullmatch(token):
            found.append(token)
    return found


def _body_rows(page: pymupdf.Page) -> list[pymupdf.Rect]:
    found: list[pymupdf.Rect] = []
    for drawing in page.get_drawings():
        rect = drawing.get("rect")
        if rect is None:
            continue
        if not (16 <= rect.height <= 32):
            continue
        if rect.width < 300 or rect.x0 > 40 or rect.x1 > 520:
            continue
        found.append(rect)
    found.sort(key=lambda rect: (rect.y0, rect.x0))
    rows: list[pymupdf.Rect] = []
    for rect in found:
        if rows and abs(rect.y0 - rows[-1].y0) < 1.5:
            continue
        rows.append(rect)
    return rows


def _blocks(rows: list[pymupdf.Rect]) -> list[list[pymupdf.Rect]]:
    blocks: list[list[pymupdf.Rect]] = []
    current: list[pymupdf.Rect] = []
    for rect in rows:
        if current and rect.y0 - current[-1].y1 > _BLOCK_GAP:
            blocks.append(current)
            current = []
        current.append(rect)
    if current:
        blocks.append(current)
    return blocks


def _layout_name(words: list[tuple]) -> str | None:
    if any(parse_grouped_amount(word[4]) is not None for word in words):
        return None
    blob = " ".join(word[4] for word in words)
    if "اکونومی" in blob and "استیل" in blob:
        return "triple"
    if "گرید" in blob and "رنگ" in blob and "شرح" in blob:
        return "grade"
    if "قیمت" in blob and "رنگ" in blob and "شرح" in blob:
        return "single"
    if "استیل" in blob and "اندازه" in blob and "شرح" in blob:
        return "steel"
    return None


def _line_groups(words: list[tuple]) -> list[list[tuple]]:
    ordered = sorted(words, key=lambda word: (_yc(word), word[0]))
    lines: list[list[tuple]] = []
    for word in ordered:
        if lines and abs(_yc(word) - _yc(lines[-1][0])) <= _LINE_Y_TOLERANCE:
            lines[-1].append(word)
        else:
            lines.append([word])
    return lines


def _anchors_for(layout: str, header_words: list[tuple]) -> list[tuple[str, float]] | None:
    remaining = sorted(header_words, key=_xc)
    anchors: list[tuple[str, float]] = []
    for role, predicate in _ANCHORS[layout]:
        found = next((word for word in remaining if predicate(word[4])), None)
        if found is None:
            return None
        remaining = [word for word in remaining if word is not found]
        anchors.append((role, _xc(found)))
    return anchors


def _bands(
    anchors: list[tuple[str, float]], *, cell_right: float
) -> list[tuple[str, float, float]]:
    ordered = sorted(anchors, key=lambda item: item[1])
    edges = [0.0]
    for (_, left), (_, right) in zip(ordered, ordered[1:]):
        edges.append((left + right) / 2.0)
    edges.append(10_000.0)
    bands = [
        (role, edges[index], edges[index + 1]) for index, (role, _) in enumerate(ordered)
    ]
    # Header labels sit in the middle of a column, so the midpoint between
    # اندازه/شرح (or رنگ/شرح) cuts into the right-hand cell. The drawn body
    # ends at the real column boundary.
    if len(bands) >= 2 and bands[-2][1] < cell_right < bands[-1][2]:
        previous = bands[-2]
        last = bands[-1]
        bands[-2] = (previous[0], previous[1], cell_right)
        bands[-1] = (last[0], cell_right, last[2])
    return bands


def _role_at(bands: list[tuple[str, float, float]], word: tuple) -> str | None:
    center = _xc(word)
    for role, left, right in bands:
        if left <= center < right:
            return role
    return None


def _row_index(rows: list[pymupdf.Rect], yc: float) -> int | None:
    best: int | None = None
    best_distance = 10_000.0
    for index, rect in enumerate(rows):
        if rect.y0 - 1.0 <= yc <= rect.y1 + 1.0:
            distance = abs(yc - (rect.y0 + rect.y1) / 2.0)
            if distance < best_distance:
                best = index
                best_distance = distance
    return best


def _page_is_one_inch(words: list[tuple]) -> bool:
    title = " ".join(word[4] for word in words if _yc(word) < 145)
    return "یک" in title and "اینچ" in title


def _descriptive_parts(
    *,
    description: str,
    length: str | None,
    color: str | None,
    one_inch: bool,
) -> list[str]:
    parts: list[str] = []
    if one_inch:
        parts.append("یک اینچ")
    if description:
        parts.append(description)
    if length and "سانت" not in description:
        parts.append(length)
    if color:
        parts.append(color)
    return parts


def _legacy_product_name(
    *,
    description: str,
    length: str | None,
    color: str | None,
    material: str | None,
    grade: str | None,
    one_inch: bool,
) -> str:
    """Name formula used before the brand and construction notes were added."""
    parts = [
        "شیلنگ",
        *_descriptive_parts(
            description=description,
            length=length,
            color=color,
            one_inch=one_inch,
        ),
    ]
    if material:
        parts.append(material)
    if grade:
        parts.append(f"گرید {grade}")
    return _polish_fragment(" ".join(parts))


def _product_name(
    *,
    description: str,
    length: str | None,
    color: str | None,
    material: str | None,
    grade: str | None,
    one_inch: bool,
) -> str:
    parts = [
        "شیلنگ",
        "کیان",
        *_descriptive_parts(
            description=description,
            length=length,
            color=color,
            one_inch=one_inch,
        ),
    ]
    if material:
        parts.append(material)
        spec = _MATERIAL_SPEC.get(material)
        if spec:
            parts.append(spec)
    if grade:
        parts.append(f"گرید {grade}")
        spec = _GRADE_SPEC.get(grade)
        if spec:
            parts.append(spec)
    return _polish_fragment(" ".join(parts))


def _texts_for_rows(
    per_row: list[str],
    words: list[tuple],
    *,
    require_primary: bool,
) -> list[str]:
    complete = bool(per_row) and all(per_row)
    if complete and (not require_primary or all(_has_primary(text) for text in per_row)):
        return per_row
    merged = _compose_description(_cluster_lines(words))
    return [merged for _ in per_row]


class KianProcessor(BaseSupplierProcessor):
    """Processor for گروه تولیدی صنعتی کیان building-hose price lists."""

    supplier_key = SUPPLIER_KEY
    display_name = SUPPLIER_DISPLAY_NAME

    def detection_rules(self) -> DetectionRules:
        return DetectionRules(
            strong_markers=("گروه تولیدی صنعتی کیان",),
            weak_markers=("اکونومی", "پیسواری", "شلنگ های پکیج"),
            supporting_markers=("مهرماه",),
            websites=(),
        )

    def calculate_final_sale_price(self, item: SupplierPriceItem) -> Decimal:
        """Convert one printed Toman amount to Rial. No second factor is applied."""
        sale = item.price * TOMAN_TO_RIAL
        integral = sale.to_integral_value()
        if integral == sale:
            return integral
        return sale

    def normalize_supplier_name(self, name: str) -> str:
        return normalize_product_name(name)

    def prior_normalized_names(self, item: SupplierPriceItem) -> tuple[str, ...]:
        legacy = item.raw_values.get("legacy_name")
        if not isinstance(legacy, str) or not legacy.strip():
            return ()
        previous = self.normalize_supplier_name(legacy)
        current = self.normalize_supplier_name(item.supplier_name)
        if not previous or previous == current:
            return ()
        return (previous,)

    def parse_pdf(self, path: str | Path) -> SupplierParseResult:
        source = Path(path)
        if not source.is_file():
            raise SupplierPdfError(f"PDF not found: {source}")

        items: list[SupplierPriceItem] = []
        warnings: list[str] = []
        page_counts: dict[int, int] = {}
        try:
            with pymupdf.open(source) as doc:
                if doc.page_count == 0:
                    raise SupplierPdfError("PDF has no pages")
                for page_index, page in enumerate(doc):
                    page_number = page_index + 1
                    page_items, page_warnings = self._parse_page(
                        page, page_number=page_number
                    )
                    items.extend(page_items)
                    warnings.extend(page_warnings)
                    page_counts[page_number] = len(page_items)
                    if page_number == 5 and not page_items:
                        text = page.get_text("text") or ""
                        if "تخفیف" in text or "بسته" in text:
                            warnings.append(
                                "page 5: packaging quantities and discount notes "
                                "were not applied"
                            )
        except SupplierPdfError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise SupplierPdfError(f"failed to read Kian PDF: {exc}") from exc

        if not items:
            raise SupplierPdfError(
                "No priced products could be extracted from the Kian PDF."
            )

        seen: dict[str, str] = {}
        for item in items:
            code = item.supplier_code or ""
            if code and code in seen:
                warnings.append(
                    f"duplicate supplier code {code} "
                    f"({seen[code]!r} and {item.supplier_name!r})"
                )
            elif code:
                seen[code] = item.supplier_name

        return SupplierParseResult(
            supplier_key=self.supplier_key,
            supplier_display_name=self.display_name,
            items=items,
            warnings=warnings,
            source_metadata={
                "source_path": str(source),
                "page_count": len(page_counts),
                "item_count": len(items),
                "items_per_page": {
                    str(page): count for page, count in page_counts.items()
                },
                "currency": PIONEERS_SALE_CURRENCY,
                "original_currency": "toman",
                "pricing_rule": "toman_times_10_to_rial",
                "package_multiplier_applied": False,
                "discount_applied": False,
                "vat_note": "PDF does not state whether VAT is included",
            },
        )

    def _parse_page(
        self, page: pymupdf.Page, *, page_number: int
    ) -> tuple[list[SupplierPriceItem], list[str]]:
        words = page.get_text("words")
        one_inch = _page_is_one_inch(words)
        layout_lines = [
            line for line in _line_groups(words) if _layout_name(line) is not None
        ]
        items: list[SupplierPriceItem] = []
        warnings: list[str] = []
        for block in _blocks(_body_rows(page)):
            block_top = block[0].y0
            header = max(
                (line for line in layout_lines if _yc(line[0]) < block_top - 2),
                default=None,
                key=lambda line: _yc(line[0]),
            )
            if header is None:
                warnings.append(f"page {page_number}: priced block has no column header")
                continue
            layout = _layout_name(header)
            if layout is None:
                continue
            anchors = _anchors_for(layout, header)
            if anchors is None:
                warnings.append(
                    f"page {page_number}: could not read the {layout} column header"
                )
                continue
            bands = _bands(anchors, cell_right=block[0].x1)
            block_bottom = block[-1].y1
            in_block = [
                word
                for word in words
                if block_top - 1 <= _yc(word) <= block_bottom + 1
            ]
            by_row: list[dict[str, list[tuple]]] = [
                {} for _ in block
            ]
            for word in in_block:
                role = _role_at(bands, word)
                if role is None:
                    continue
                index = _row_index(block, _yc(word))
                if index is None:
                    continue
                by_row[index].setdefault(role, []).append(word)

            per_row_desc = [
                _compose_description(_cluster_lines(row.get("description", [])))
                for row in by_row
            ]
            descriptions = _texts_for_rows(
                per_row_desc,
                [word for word in in_block if _role_at(bands, word) == "description"],
                require_primary=True,
            )
            per_row_color = [
                _compose_description(_cluster_lines(row.get("color", [])))
                for row in by_row
            ]
            colors = _texts_for_rows(
                per_row_color,
                [word for word in in_block if _role_at(bands, word) == "color"],
                require_primary=False,
            )

            for index, row in enumerate(by_row):
                length = _length_text(row.get("size", []))
                description = descriptions[index]
                color = colors[index] or None
                if not description:
                    if any(row.get(role) for role, _, _, _ in _VARIANTS[layout]):
                        warnings.append(
                            f"page {page_number}: row without a product description"
                        )
                    continue
                for price_role, code_role, material, grade in _VARIANTS[layout]:
                    cell = _read_price_cell(row.get(price_role, []))
                    codes = _codes(row.get(code_role, []))
                    if cell.kind in {"absent", "dashed"}:
                        if cell.kind == "absent" and len(codes) == 1:
                            warnings.append(
                                f"page {page_number}: missing price for code {codes[0]}"
                            )
                        continue
                    if len(codes) != 1 or cell.kind == "unreadable" or cell.amount is None:
                        warnings.append(
                            f"page {page_number}: unreadable price/code "
                            f"in {price_role} (price={cell.text!r}, codes={codes!r})"
                        )
                        continue
                    name_fields = {
                        "description": description,
                        "length": length,
                        "color": color,
                        "material": material,
                        "grade": grade,
                        "one_inch": one_inch,
                    }
                    blockers = [cell.blocker] if cell.blocker else []
                    items.append(
                        SupplierPriceItem(
                            supplier_id=self.supplier_key,
                            supplier_code=codes[0],
                            supplier_name=_product_name(**name_fields),
                            price=cell.amount,
                            raw_values={
                                "currency": PIONEERS_SALE_CURRENCY,
                                "original_currency": "toman",
                                "original_price": format(cell.amount, "f"),
                                "original_price_text": cell.text,
                                "price_basis": PRICE_BASIS_PRINTED,
                                "tax": "not_stated",
                                "page": page_number,
                                "material": material,
                                "grade": grade,
                                "color": color,
                                "length": length,
                                "legacy_name": _legacy_product_name(**name_fields),
                                "review_warnings": [],
                                "pricing_blockers": blockers,
                            },
                        )
                    )
        return items, warnings
