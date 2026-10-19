"""Abstract supplier processor contract."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any, Sequence

from gheymatyar.domain.supplier_item import SupplierPriceItem


@dataclass(frozen=True)
class SupplierParseResult:
    """Standardized output every supplier processor must return."""

    supplier_key: str
    supplier_display_name: str
    items: list[SupplierPriceItem]
    warnings: list[str] = field(default_factory=list)
    source_metadata: dict[str, Any] = field(default_factory=dict)


class BaseSupplierProcessor(ABC):
    """One processor per supplier PDF format / pricing ruleset."""

    #: Stable machine key used in API / registry (e.g. ``azin_pipe``).
    supplier_key: str
    #: Human-readable label for UI dropdowns.
    display_name: str

    @abstractmethod
    def parse_pdf(self, path: str | Path) -> SupplierParseResult:
        """Extract priced products from this supplier's PDF."""

    def calculate_final_sale_price(self, item: SupplierPriceItem) -> Decimal:
        """Map an extracted supplier price to the Pioneers final sale price.

        Default: direct replacement. Override only when the supplier's
        business rules are explicitly defined.
        """
        return item.price

    def normalize_supplier_name(self, name: str) -> str:
        """Optional supplier-specific name transform before shared matching."""
        return name

    def matching_hints(self, item: SupplierPriceItem) -> Sequence[str]:
        """Optional alternate names used only as suggestion seeds."""
        return ()
