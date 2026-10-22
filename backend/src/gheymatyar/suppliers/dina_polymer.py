"""دینا پلیمر (Dina Polymer) price-list processor.

The sample is a 4-page Gitikala export. PyMuPDF word positions are used
because pdfplumber interleaves the two-column Persian headers.

Pipe sections state قیمت هر متر on page 1. Later pipe tables repeat the
same قیمت / متراژ columns. متراژ (branch or roll length) is package size
and is never multiplied into the price. Fitting rows are per piece.

The fitting table prints prices under an Excel ``#N/A`` header. Those
amounts are kept and blocked from automatic export.

The PDF does not say whether VAT is included. No tax is added or removed.
"""

from __future__ import annotations

import re
from decimal import Decimal
from pathlib import Path

import pymupdf

from gheymatyar.domain.supplier_item import SupplierPriceItem
from gheymatyar.services.name_normalization import normalize_product_name
from gheymatyar.suppliers.base import BaseSupplierProcessor, SupplierParseResult
from gheymatyar.suppliers.errors import SupplierPdfError
from gheymatyar.suppliers.textutil import contains_arabic, parse_grouped_amount, polish_persian

SUPPLIER_KEY = "dina_polymer"
SUPPLIER_DISPLAY_NAME = "دینا پلیمر"

FITTING_HEADER_WARNING = (
    "fitting price sits under a #N/A column header; "
    "the numeric cell was kept as a per-piece Rial price and "
    "automatic export is blocked until that column is confirmed"
)

_CODE_RE = re.compile(r"^8\d{8}$")


def _lines(page: pymupdf.Page) -> list[list[tuple]]:
    words = page.get_text("words")
    lines: list[list[tuple]] = []
    for word in sorted(words, key=lambda item: (item[1], item[0])):
        if lines and abs(word[1] - lines[-1][0][1]) <= 2.0:
            lines[-1].append(word)
        else:
            lines.append([word])
    return lines


def _text_of(words: list[tuple]) -> str:
    return " ".join(word[4] for word in sorted(words, key=lambda item: item[0]))


def _is_header(text: str) -> bool:
    compact = text.replace(" ", "")
    has_code = "کدکالا" in compact or "کدکاال" in compact
    if not has_code:
        return False
    return "قیمت" in compact or "نام" in text


def _header_mode(text: str) -> str:
    if "نام" in text and "قیمت" not in text:
        return "fitting"
    if "فشار" in text:
        return "pressure"
    if "فاصله" in text or "چکان" in text:
        return "drip"
    return "pipe"


def _split_halves(words: list[tuple]) -> list[list[tuple]]:
    codes = [word for word in words if _CODE_RE.fullmatch(word[4])]
    if len(codes) >= 2:
        ordered = sorted(codes, key=lambda word: word[0])
        mid = (ordered[0][2] + ordered[1][0]) / 2
        return [
            [word for word in words if word[0] < mid],
            [word for word in words if word[0] >= mid],
        ]
    if len(codes) == 1:
        return [words]
    ordered = sorted(words, key=lambda word: word[0])
    widest = 0.0
    split_at: float | None = None
    for left, right in zip(ordered, ordered[1:]):
        gap = right[0] - left[2]
        if gap > widest:
            widest = gap
            split_at = (left[2] + right[0]) / 2
    if split_at is not None and widest > 28:
        return [
            [word for word in words if word[0] < split_at],
            [word for word in words if word[0] >= split_at],
        ]
    return [words]


def _category_text(words: list[tuple]) -> str | None:
    raw = _text_of(words)
    if not raw or "لیست" in raw or "ISO" in raw or "SITE" in raw or "Telegram" in raw:
        return None
    if not any(token in raw for token in ("PE", "آبیاری", "اتصالات", "اتصاالت")):
        return None
    persian: list[str] = []
    for word in sorted(words, key=lambda item: item[0]):
        token = word[4].strip("()")
        if contains_arabic(token) and not re.search(r"[A-Za-z0-9]", token):
            persian.append(polish_persian(token))
    phrase = " ".join(reversed([part for part in persian if part]))
    specs = re.findall(
        r"PE\s*-?\s*\d+|SDR\s*-?\s*[\d.]+|\d+(?:\.\d+)?\s*bar",
        raw,
        flags=re.IGNORECASE,
    )
    spec_text = " ".join(spec.replace(" ", "") if spec.lower().startswith("pe") else spec for spec in specs)
    # Keep a readable space in "6 bar" / "SDR 26".
    spec_text = re.sub(r"(?i)PE\s*-?\s*", "PE", spec_text)
    spec_text = re.sub(r"(?i)SDR\s*-?\s*", "SDR ", spec_text)
    label = polish_persian(f"{phrase} {spec_text}".strip())
    label = re.sub(r"\s+", " ", label).strip(" -")
    return label or None


def _without_center_row_numbers(words: list[tuple], page_width: float) -> list[tuple]:
    """Drop the gutter row number that sits between the two price columns.

    On terminal rows that number (170–172, 377–379, …) is not a branch length.
    Real meterage is the ``12-`` token beside شاخه.
    """
    center = page_width / 2
    kept: list[tuple] = []
    for word in words:
        text = str(word[4])
        midpoint = (float(word[0]) + float(word[2])) / 2
        if abs(midpoint - center) <= 18 and re.fullmatch(r"\d{1,3}", text):
            continue
        kept.append(word)
    return kept


def _column_side(words: list[tuple], page_width: float) -> int:
    """0 = left price column, 1 = right. Side follows the product code's x."""
    codes = [word for word in words if _CODE_RE.fullmatch(word[4])]
    if not codes:
        return 0
    return 0 if float(codes[-1][0]) < page_width / 2 else 1


def _meterage(tokens: list[str]) -> tuple[str | None, str | None, list[str]]:
    """Return length, form, and the tokens that were not part of the meterage.

    Length is the number immediately beside شاخه/رول, not the first integer on
    the line. A gutter row number must not become a 170 m branch.
    """
    form = None
    if any("رول" in token for token in tokens):
        form = "رولی"
    elif any("شاخه" in token for token in tokens):
        form = "شاخه ای"
    consumed: set[int] = set()
    length: str | None = None
    if form:
        form_index = next(
            index
            for index, token in enumerate(tokens)
            if "شاخه" in token or "رول" in token
        )
        for index in range(form_index, -1, -1):
            token = tokens[index]
            if "شاخه" in token or "رول" in token or token in {"ای", "اي", "-", "–", "—"}:
                consumed.add(index)
                continue
            if re.fullmatch(r"\d{1,4}-?", token):
                length = token.rstrip("-")
                consumed.add(index)
            break
    kept = [
        token
        for index, token in enumerate(tokens)
        if index not in consumed and token not in {"-", "–", "—"}
    ]
    return length, form, kept


def _interpret(rest: list[str], mode: str) -> dict[str, str | None]:
    length, form, kept = _meterage(rest)
    ignored: list[str] = []
    numbers: list[str] = []
    others: list[str] = []
    for token in kept:
        if re.fullmatch(r"\d{5,}", token):
            # Unseparated 5+ digit values are the #N/A drip column, not prices.
            ignored.append(token)
            continue
        if re.fullmatch(r"\d+", token):
            numbers.append(token)
        else:
            others.append(token)
    size = None
    pressure = None
    spacing = None
    if others and not numbers:
        size = " ".join(others)
    elif numbers:
        size = numbers[-1]
        remaining = numbers[:-1]
        if mode == "pressure" and remaining:
            pressure = remaining[-1]
        elif mode == "drip" and remaining:
            spacing = remaining[-1]
        elif mode == "pipe" and length is None and remaining:
            length = remaining[0]
        if others:
            size = f"{size} {' '.join(others)}".strip()
    return {
        "size": size,
        "length": length,
        "form": form,
        "pressure": pressure,
        "spacing": spacing,
        "ignored": ",".join(ignored) or None,
    }


def _parse_group(
    words: list[tuple], mode: str
) -> dict[str, str | None] | None:
    ordered = sorted(words, key=lambda word: word[0])
    texts = [word[4] for word in ordered]
    code_indexes = [index for index, text in enumerate(texts) if _CODE_RE.fullmatch(text)]
    if not code_indexes:
        return None
    index = code_indexes[-1]
    code = texts[index]
    before = texts[:index]
    after = texts[index + 1 :]
    price_text = next((token for token in before if parse_grouped_amount(token)), None)
    if price_text is None:
        return {"code": code, "price_text": None}
    rest = [token for token in before if token != price_text]
    fields = _interpret(rest, mode)
    name_words = [polish_persian(token) for token in reversed(after) if token.strip()]
    # Drop a trailing row number that sometimes follows the name.
    while name_words and re.fullmatch(r"\d{1,3}", name_words[-1]):
        name_words.pop()
    fields.update(
        {
            "code": code,
            "price_text": price_text,
            "row_name": " ".join(name_words).strip() or None,
        }
    )
    return fields


def _display_name(category: str | None, fields: dict[str, str | None], *, fitting: bool) -> str | None:
    size = fields.get("size")
    if fitting and fields.get("row_name"):
        parts = ["دینا", fields["row_name"]]
        if size:
            parts.append(size)
        return re.sub(r"\s+", " ", " ".join(parts)).strip()
    if not category and not size:
        return None
    parts = ["دینا"]
    if category:
        parts.append(category)
    if size:
        parts.append(f"سایز {size}")
    if fields.get("pressure"):
        parts.append(f"فشار {fields['pressure']}")
    if fields.get("spacing"):
        parts.append(f"فاصله {fields['spacing']}")
    if fields.get("form") and fields.get("length"):
        parts.append(f"{fields['form']} {fields['length']} متر")
    elif fields.get("form"):
        parts.append(str(fields["form"]))
    return re.sub(r"\s+", " ", " ".join(parts)).strip()


class DinaPolymerProcessor(BaseSupplierProcessor):
    """Processor for لیست قیمت لوله و اتصالات دینا پلیمر."""

    supplier_key = SUPPLIER_KEY
    display_name = SUPPLIER_DISPLAY_NAME

    def parse_pdf(self, path: str | Path) -> SupplierParseResult:
        source = Path(path)
        if not source.is_file():
            raise SupplierPdfError(f"PDF not found: {source}")

        items: list[SupplierPriceItem] = []
        warnings: list[str] = []
        seen: set[str] = set()
        per_meter_stated = False
        page_count = 0
        try:
            doc = pymupdf.open(source)
        except Exception as exc:  # noqa: BLE001
            raise SupplierPdfError(f"failed to read Dina PDF: {exc}") from exc
        try:
            page_count = doc.page_count
            if page_count == 0:
                raise SupplierPdfError("PDF has no pages")
            first = doc[0].get_text("text") or ""
            if "دینا" not in first:
                warnings.append(
                    "PDF does not clearly identify as دینا پلیمر; "
                    "parsing will still be attempted"
                )
            for page_index, page in enumerate(doc):
                page_text = page.get_text("text") or ""
                if "هر متر" in page_text or "متر هر" in page_text:
                    per_meter_stated = True
                page_items, page_warnings = self._parse_page(
                    page,
                    page_number=page_index + 1,
                    seen=seen,
                    per_meter=per_meter_stated or "هر متر" in page_text or "متر هر" in page_text,
                )
                items.extend(page_items)
                warnings.extend(page_warnings)
        finally:
            doc.close()

        if not items:
            raise SupplierPdfError(
                "No priced products could be extracted from the Dina PDF."
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
                "pricing_rule": "printed_amount_per_stated_basis",
                "vat_note": "PDF does not state whether VAT is included",
                "per_meter_header": per_meter_stated,
            },
        )

    def calculate_final_sale_price(self, item: SupplierPriceItem) -> Decimal:
        return item.price

    def normalize_supplier_name(self, name: str) -> str:
        return normalize_product_name(name)

    def _parse_page(
        self,
        page: pymupdf.Page,
        *,
        page_number: int,
        seen: set[str],
        per_meter: bool,
    ) -> tuple[list[SupplierPriceItem], list[str]]:
        items: list[SupplierPriceItem] = []
        warnings: list[str] = []
        mode = "pipe"
        pending: list[tuple] = []
        categories: list[str | None] = [None, None]

        def flush_category() -> None:
            if not pending:
                return
            halves = _split_halves(pending)
            labels = [_category_text(half) for half in halves]
            labels = [label for label in labels if label]
            if len(labels) >= 2:
                categories[0] = labels[0]
                categories[1] = labels[1]
            elif len(labels) == 1:
                categories[0] = labels[0]
                categories[1] = labels[0]
            pending.clear()

        for line in _lines(page):
            text = _text_of(line)
            if not text or "WEB SITE" in text or "Telegram" in text:
                continue
            if _is_header(text):
                flush_category()
                mode = _header_mode(text)
                continue
            if any(_CODE_RE.fullmatch(word[4]) for word in line):
                flush_category()
                groups = _split_halves(
                    _without_center_row_numbers(line, page.rect.width)
                )
                for group in groups:
                    parsed = _parse_group(group, mode)
                    if not parsed:
                        continue
                    side = _column_side(group, page.rect.width)
                    item, warn = self._build_item(
                        parsed,
                        category=categories[side],
                        mode=mode,
                        page_number=page_number,
                        per_meter=per_meter,
                        seen=seen,
                    )
                    if item:
                        items.append(item)
                    if warn:
                        warnings.append(warn)
                continue
            if any(token in text for token in ("PE", "آبیاری", "اتصالات", "اتصاالت")) and "ISO" not in text and "لیست" not in text:
                pending.extend(line)
        flush_category()
        return items, warnings

    def _build_item(
        self,
        parsed: dict[str, str | None],
        *,
        category: str | None,
        mode: str,
        page_number: int,
        per_meter: bool,
        seen: set[str],
    ) -> tuple[SupplierPriceItem | None, str | None]:
        code = parsed.get("code") or ""
        if code in seen:
            return None, f"page {page_number}: duplicate supplier code {code} skipped"
        price = parse_grouped_amount(parsed.get("price_text"))
        if price is None:
            return (
                None,
                f"page {page_number}: unreadable price for code {code} "
                f"({parsed.get('price_text')!r})",
            )
        fitting = mode == "fitting"
        name = _display_name(category, parsed, fitting=fitting)
        if not name:
            return None, f"page {page_number}: missing category for code {code}; row skipped"
        if not fitting and not category:
            return None, f"page {page_number}: missing category for code {code}; row skipped"

        basis = "piece" if fitting else ("meter" if per_meter or mode in {"pipe", "pressure", "drip"} else "listed")
        length = parsed.get("length")
        review: list[str] = []
        if fitting:
            review.append(FITTING_HEADER_WARNING)
        elif parsed.get("form") == "شاخه ای" and (
            not length or not str(length).isdigit() or int(str(length)) > 24
        ):
            review.append(
                "branch length is missing or not a printed 6–12 m branch; "
                "automatic export is blocked until the dimension is confirmed"
            )
        seen.add(code)
        return (
            SupplierPriceItem(
                supplier_id=self.supplier_key,
                supplier_code=code,
                supplier_name=name,
                price=price,
                unit="متر" if basis == "meter" else "عدد",
                raw_values={
                    "currency": "rial",
                    "original_price": str(price),
                    "original_price_text": parsed.get("price_text"),
                    "price_basis": basis,
                    "tax": "not_stated",
                    "page": page_number,
                    "section": category,
                    "size": parsed.get("size"),
                    "pressure_bar": parsed.get("pressure"),
                    "drip_spacing_cm": parsed.get("spacing"),
                    "package_length_m": length,
                    "package_form": parsed.get("form"),
                    "ignored_column": parsed.get("ignored"),
                    "review_warnings": review,
                    "pricing_blockers": list(review),
                },
            ),
            None,
        )
