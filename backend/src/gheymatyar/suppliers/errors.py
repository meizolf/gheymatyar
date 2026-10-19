"""Supplier processing errors."""


class SupplierError(Exception):
    """Base class for supplier processing failures."""


class SupplierPdfError(SupplierError):
    """The PDF could not be parsed for this supplier."""


class UnsupportedSupplierError(SupplierError):
    """No processor is registered for the requested supplier key."""
