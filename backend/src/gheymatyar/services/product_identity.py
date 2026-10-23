"""Stable supplier-product identity for persistent user decisions.

Decisions are not keyed by session id, PDF filename, Excel row, or PDF version.
The key is the supplier (stored separately) plus the normalized product name and
the attributes that distinguish variants: supplier code and unit.
"""

from __future__ import annotations

from collections.abc import Callable

from gheymatyar.services.name_normalization import (
    normalize_digits,
    normalize_product_name,
)

# Unit separator that cannot appear in a normalized product name.
_SEP = "\x1f"


def supplier_product_identity(
    *,
    normalized_name: str,
    supplier_code: str | None = None,
    unit: str | None = None,
) -> str:
    """Build the identity key from an already normalized supplier name.

    ``normalized_name`` must be the same string the matcher uses for saved
    mappings (the supplier processor's ``normalize_supplier_name``).
    """
    name = normalized_name.strip()
    if not name:
        raise ValueError("product identity requires a normalized name")
    code = ""
    if supplier_code and str(supplier_code).strip():
        code = normalize_digits(str(supplier_code).strip())
    unit_norm = ""
    if unit and str(unit).strip():
        unit_norm = normalize_product_name(str(unit))
    return _SEP.join((name, code, unit_norm))


def decision_identity(
    name: str,
    *,
    supplier_code: str | None,
    unit: str | None,
    normalize_name: Callable[[str], str],
) -> str:
    """Identity for a raw supplier name using the supplier's normalizer."""
    return supplier_product_identity(
        normalized_name=normalize_name(name),
        supplier_code=supplier_code,
        unit=unit,
    )
