"""Size and label helpers for galvanized and threaded fitting price lists.

These lists print inch sizes as ``1/2"``, ``1 1/4"`` or ``2 1/2"``. Some
write the mixed fractions run together (``11/4`` for 1 1/4, ``21/2`` for
2 1/2), and pdfplumber can return the two parts of a mixed fraction in
either order (``1/4 1`` or ``1/4-1``). Sizes are therefore read by their
parts, not by string order.
"""

from __future__ import annotations

import re

from gheymatyar.services.name_normalization import normalize_digits

_GROUP_SPLIT = re.compile(r"[×*xX]")
_FRACTION = re.compile(r"^\d+/\d+$")
_WHOLE = re.compile(r"^\d+$")
# 11/4, 11/2, 13/4, 21/2, 31/2: a whole inch and a fraction written together.
_RUN_TOGETHER = re.compile(r"^([1-3])(1/[24]|3/4)$")
_ANGLE = re.compile(r"(\d+)\s*درجه")


def inch_part(text: str) -> str | None:
    """One size: ``"1 1/4"``, ``"3/4"`` or ``"2"``; None if not a single size."""
    tokens = [t for t in re.split(r"[\s\-\"'″]+", normalize_digits(text)) if t]
    if len(tokens) == 1:
        run = _RUN_TOGETHER.match(tokens[0])
        if run:
            return f"{run.group(1)} {run.group(2)}"
        if _FRACTION.match(tokens[0]) or _WHOLE.match(tokens[0]):
            return tokens[0]
        return None
    if len(tokens) == 2:
        wholes = [t for t in tokens if _WHOLE.match(t)]
        fractions = [t for t in tokens if _FRACTION.match(t)]
        if len(wholes) == 1 and len(fractions) == 1:
            return f"{wholes[0]} {fractions[0]}"
    return None


def size_groups(text: str) -> list[str] | None:
    """``"40×11/4"`` → ``["40", "1 1/4"]``. None if any part is not a size."""
    parts = [part for part in _GROUP_SPLIT.split(normalize_digits(text)) if part.strip()]
    sizes = [inch_part(part) for part in parts]
    if not sizes or any(size is None for size in sizes):
        return None
    return [size for size in sizes if size is not None]


def split_label(label: str) -> tuple[str, list[str]]:
    """Product words and sizes from a row label.

    ``'تبدیل " 1 1/4'`` → ``("تبدیل", ["1 1/4"])``; ``'زانو 45 درجه'`` keeps
    the angle in the name; ``'روپیچ 1/2" کوتاه'`` → ``("روپیچ کوتاه", ["1/2"])``.
    """
    text = normalize_digits(label).replace("″", '"')
    angles = [f"{m.group(1)} درجه" for m in _ANGLE.finditer(text)]
    text = _ANGLE.sub(" ", text)
    words = [w for w in re.findall(r"[^\s\"'×*\d/\-]+", text) if re.search(r"[؀-ۿ]", w)]
    numeric = re.sub(r"[^\d/×*\s\-]", " ", text)
    sizes = size_groups(numeric) if re.search(r"\d", numeric) else []
    name = " ".join(words + angles) if not angles else _with_angles(words, angles)
    return " ".join(name.split()), sizes or []


def _with_angles(words: list[str], angles: list[str]) -> str:
    # The angle follows the fitting type: «زانو 45 درجه».
    if not words:
        return " ".join(angles)
    return " ".join([words[0], *angles, *words[1:]])


def size_text(sizes: list[str]) -> str:
    """``["1 1/4", "1"]`` → ``1 1/4"×1"``."""
    return "×".join(f'{size}"' for size in sizes)
