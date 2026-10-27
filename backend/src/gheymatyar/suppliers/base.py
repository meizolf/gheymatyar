"""Abstract supplier processor contract."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any, Sequence

from gheymatyar.domain.supplier_item import SupplierPriceItem
from gheymatyar.suppliers.detection import (
    DetectionRules,
    extract_pdf_text_for_detection,
    matching_strong_markers,
    try_offline_ocr,
)
from gheymatyar.suppliers.errors import SupplierPdfError


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
    #: ``pdf`` for an uploaded price list, ``website`` for a fetched page.
    source_kind: str = "pdf"

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

    def prior_normalized_names(self, item: SupplierPriceItem) -> Sequence[str]:
        """Earlier normalized names for this same code and unit.

        Used only to keep a saved mapping or ignore after a name formula
        changes. The result is never a code-only lookup.
        """
        return ()

    def detection_rules(self) -> DetectionRules:
        """Content markers used by :class:`SupplierDetector`.

        Override in each processor so adding a supplier only requires
        registering rules alongside the parser — never in the React UI.
        """
        return DetectionRules()

    def read_pdf_identity_text(self, path: str | Path) -> str:
        """Full-document text used for confirmation identity checks."""
        source = Path(path)
        if not source.is_file():
            raise SupplierPdfError(f"PDF not found: {source}")
        text, has_text = extract_pdf_text_for_detection(source, max_pages=None)
        if has_text:
            return text
        return try_offline_ocr(source, max_pages=2)

    def validate_pdf_identity(self, path: str | Path, *, text: str | None = None) -> None:
        """Require a strong brand/identity marker before parsing prices.

        An identity *warning* during parse is not enough — confirmation must
        fail hard when the PDF does not belong to this supplier. Callers that
        also check for foreign brands should pass precomputed ``text``.
        """
        body = text if text is not None else self.read_pdf_identity_text(path)
        rules = self.detection_rules()
        if not rules.strong_markers:
            raise SupplierPdfError(
                f"supplier {self.supplier_key!r} has no identity markers configured"
            )
        if not matching_strong_markers(body, rules):
            raise SupplierPdfError(
                f"PDF does not identify as {self.display_name}; "
                f"refusing supplier {self.supplier_key!r}"
            )
