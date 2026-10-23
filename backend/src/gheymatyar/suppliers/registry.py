"""Registry of supplier processors."""

from __future__ import annotations

from dataclasses import dataclass

from pathlib import Path

from gheymatyar.suppliers.abrahan_pipe import AbrahanPipeProcessor
from gheymatyar.suppliers.azin_pipe import AzinPipeProcessor
from gheymatyar.suppliers.base import BaseSupplierProcessor
from gheymatyar.suppliers.detection import (
    DetectionResult,
    SupplierDetector,
    matching_strong_markers,
)
from gheymatyar.suppliers.dina_polymer import DinaPolymerProcessor
from gheymatyar.suppliers.errors import SupplierPdfError, UnsupportedSupplierError
from gheymatyar.suppliers.newpipe import NewPipeProcessor
from gheymatyar.suppliers.top_industrial import TopIndustrialProcessor

__all__ = [
    "SupplierInfo",
    "SupplierProcessorRegistry",
    "UnsupportedSupplierError",
    "get_default_registry",
]


@dataclass(frozen=True)
class SupplierInfo:
    key: str
    display_name: str


class SupplierProcessorRegistry:
    """Maps supplier keys to processor instances."""

    def __init__(self) -> None:
        self._processors: dict[str, BaseSupplierProcessor] = {}

    def register(self, processor: BaseSupplierProcessor) -> None:
        key = processor.supplier_key.strip()
        if not key:
            raise ValueError("supplier_key must be non-empty")
        if key in self._processors:
            raise ValueError(f"supplier already registered: {key}")
        self._processors[key] = processor

    def get(self, supplier_key: str) -> BaseSupplierProcessor:
        key = supplier_key.strip()
        processor = self._processors.get(key)
        if processor is None:
            supported = ", ".join(sorted(self._processors)) or "(none)"
            raise UnsupportedSupplierError(
                f"Unsupported supplier: {key!r}. Supported: {supported}"
            )
        return processor

    def list_suppliers(self) -> list[SupplierInfo]:
        return [
            SupplierInfo(key=p.supplier_key, display_name=p.display_name)
            for p in sorted(self._processors.values(), key=lambda p: p.supplier_key)
        ]

    def keys(self) -> list[str]:
        return sorted(self._processors)

    def detect(self, path: str | Path) -> DetectionResult:
        """Identify the most likely registered supplier from PDF content."""
        return SupplierDetector(self).detect(path)

    def validate_pdf_for_supplier(self, path: str | Path, supplier_key: str) -> None:
        """Ensure the PDF matches ``supplier_key`` and no other registered brand.

        Finding one matching brand must not authorize pages that belong to a
        different supported supplier.
        """
        processor = self.get(supplier_key)
        text = processor.read_pdf_identity_text(path)
        processor.validate_pdf_identity(path, text=text)

        conflicts: list[str] = []
        for info in self.list_suppliers():
            if info.key == processor.supplier_key:
                continue
            other = self.get(info.key)
            hits = matching_strong_markers(text, other.detection_rules())
            if hits:
                conflicts.append(other.display_name)
        if conflicts:
            names = "، ".join(conflicts)
            raise SupplierPdfError(
                f"PDF also identifies as {names}; "
                f"refusing mixed supplier document for {processor.display_name}"
            )


_DEFAULT: SupplierProcessorRegistry | None = None


def get_default_registry() -> SupplierProcessorRegistry:
    """Return the process-wide registry with built-in suppliers."""
    global _DEFAULT
    if _DEFAULT is None:
        registry = SupplierProcessorRegistry()
        registry.register(AzinPipeProcessor())
        registry.register(TopIndustrialProcessor())
        registry.register(DinaPolymerProcessor())
        registry.register(NewPipeProcessor())
        registry.register(AbrahanPipeProcessor())
        _DEFAULT = registry
    return _DEFAULT
