"""Pluggable supplier PDF processors."""

from gheymatyar.suppliers.base import BaseSupplierProcessor, SupplierParseResult
from gheymatyar.suppliers.registry import (
    SupplierProcessorRegistry,
    UnsupportedSupplierError,
    get_default_registry,
)

__all__ = [
    "BaseSupplierProcessor",
    "SupplierParseResult",
    "SupplierProcessorRegistry",
    "UnsupportedSupplierError",
    "get_default_registry",
]
