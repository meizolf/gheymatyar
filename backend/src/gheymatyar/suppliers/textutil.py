"""Small text helpers shared by supplier PDF processors.

Monetary parsing stays in Decimal. Thousands separators are accepted only as
grouping characters; they are never treated as a decimal point.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

from gheymatyar.services.name_normalization import normalize_digits

_ARABIC_RE = re.compile(r"[\u0600-\u06FF]")
_GROUPED_RE = re.compile(r"^\d{1,3}([.,]\d{3})+$")

# Font / extraction artifacts seen across these price lists.
_ARTIFACTS: tuple[tuple[str, str], ...] = (
    ("الیه", "لایه"),
    ("اطالع", "اطلاع"),
    ("اتصاالت", "اتصالات"),
    ("باال", "بالا"),
    ("فاضالبی", "فاضلابی"),
    ("ك", "ک"),
    ("ي", "ی"),
    ("ى", "ی"),
)


def contains_arabic(text: str) -> bool:
    return bool(text and _ARABIC_RE.search(text))


def polish_persian(text: str) -> str:
    """Apply known glyph artifacts and collapse whitespace. Does not reverse text."""
    cleaned = normalize_digits(text or "")
    for src, dst in _ARTIFACTS:
        cleaned = cleaned.replace(src, dst)
    cleaned = cleaned.replace("ـ", "")
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" -")
    return cleaned


def parse_grouped_amount(raw: str | None) -> Decimal | None:
    """Parse an integer amount that uses ``,`` or ``.`` as a thousands separator.

    Returns None for blank, non-numeric, mixed-separator, or non-positive values.
    A bare integer with no separator is rejected so package quantities are not
    read as prices by callers that require grouped amounts.
    """
    if raw is None:
        return None
    text = normalize_digits(str(raw))
    text = (
        text.replace(" ", "")
        .replace("\u066c", ",")  # Arabic thousands
        .replace("\u060c", ",")  # Arabic comma
        .replace("٬", ",")
        .strip()
    )
    if not text or text in {"-", "—", "#N/A"}:
        return None
    if any(mark in text for mark in ("#", "N/A", "موجود")):
        return None
    if "," in text and "." in text:
        return None
    if not _GROUPED_RE.fullmatch(text):
        return None
    digits = text.replace(",", "").replace(".", "")
    try:
        amount = Decimal(digits)
    except InvalidOperation:
        return None
    if amount <= 0:
        return None
    return amount
