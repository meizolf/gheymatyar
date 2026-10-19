"""Registry of supplier processors."""

from __future__ import annotations

from dataclasses import dataclass

from gheymatyar.suppliers.azin_pipe import AzinPipeProcessor
from gheymatyar.suppliers.base import BaseSupplierProcessor
from gheymatyar.suppliers.errors import UnsupportedSupplierError

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


_DEFAULT: SupplierProcessorRegistry | None = None


def get_default_registry() -> SupplierProcessorRegistry:
    """Return the process-wide registry with built-in suppliers."""
    global _DEFAULT
    if _DEFAULT is None:
        registry = SupplierProcessorRegistry()
        registry.register(AzinPipeProcessor())
        _DEFAULT = registry
    return _DEFAULT
