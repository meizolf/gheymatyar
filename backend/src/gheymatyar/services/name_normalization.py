"""Conservative Persian/Arabic product-name normalization."""

from __future__ import annotations

import re
import unicodedata

# Arabic → Persian letter forms commonly mixed in Iranian business docs.
_ARABIC_TO_PERSIAN = str.maketrans(
    {
        "ك": "ک",
        "ي": "ی",
        "ى": "ی",
        "ة": "ه",
        "ؤ": "و",
        "إ": "ا",
        "أ": "ا",
        "آ": "ا",
        "ٱ": "ا",
        "ٔ": "",
        "ٕ": "",
        "‌": "",  # ZWNJ
        "‍": "",  # ZWJ
        "\u0640": "",  # tatweel
    }
)

_PERSIAN_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789")
_ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")

# Common PDF / font artifacts seen in the Azin price list.
_SPELLING_FIXES: tuple[tuple[str, str], ...] = (
    ("الیه", "لایه"),
    ("اطالع", "اطلاع"),
    ("اتصاالت", "اتصالات"),
    ("باال", "بالا"),
    ("پالستیک", "پلاستیک"),
    ("فلزى", "فلزی"),
    ("مغزى", "مغزی"),
    ("دیوارى", "دیواری"),
    ("رادیاتورى", "رادیاتوری"),
    ("تلفیقى", "تلفیقی"),
    ("سه راهى", "سه راهی"),
    ("شیر مغزى", "شیر مغزی"),
    ("شیرفلکه", "شیر فلکه"),
    ("دوسربوشن", "دوسر بوشن"),
    ("pp-rct", "pprct"),
    ("pp.rct", "pprct"),
    ("pp.r", "ppr"),
    ("pp rct", "pprct"),
)

_WHITESPACE_RE = re.compile(r"\s+")
_QUOTE_RE = re.compile(r'["""\'`]+')
_SIZE_SPACE_RE = re.compile(r"\s*([*/×xX])\s*")


def normalize_digits(text: str) -> str:
    """Map Persian and Arabic-Indic digits to ASCII 0-9."""
    return text.translate(_PERSIAN_DIGITS).translate(_ARABIC_DIGITS)


def normalize_product_name(name: str) -> str:
    """Normalize a product name for conservative exact matching.

    Steps: Unicode NFKC, Arabic→Persian letters, digit folding, spelling
    artifact fixes, quote stripping, whitespace collapse, lowercasing of
    Latin letters. Does not drop meaningful tokens.
    """
    if not isinstance(name, str):
        raise TypeError("name must be a string")

    text = unicodedata.normalize("NFKC", name)
    text = text.translate(_ARABIC_TO_PERSIAN)
    text = normalize_digits(text)
    text = _QUOTE_RE.sub(" ", text)
    text = text.replace("٫", ".").replace("،", " ")
    text = text.lower()
    for src, dst in _SPELLING_FIXES:
        text = text.replace(src, dst)
    text = _SIZE_SPACE_RE.sub(r"\1", text)
    text = _WHITESPACE_RE.sub(" ", text).strip()
    return text


def tokenize_normalized_name(normalized: str) -> frozenset[str]:
    """Split a normalized name into tokens for similarity hints."""
    if not normalized:
        return frozenset()
    parts = re.split(r"[\s*_/,.\-]+", normalized)
    return frozenset(p for p in parts if p)


def name_similarity(a: str, b: str) -> float:
    """Jaccard similarity over normalized tokens in ``[0, 1]``."""
    ta = tokenize_normalized_name(normalize_product_name(a))
    tb = tokenize_normalized_name(normalize_product_name(b))
    if not ta or not tb:
        return 0.0
    inter = len(ta & tb)
    union = len(ta | tb)
    return inter / union if union else 0.0
