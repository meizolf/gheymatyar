"""Repository-layer exceptions (not HTTP / domain validation errors)."""


class RepositoryError(Exception):
    """Base class for explicit persistence failures."""


class MappingConflictError(RepositoryError):
    """Raised when creating a mapping that conflicts with an existing one.

    Conflicting means the same ``(supplier_id, supplier_code)`` already exists.
    Callers must use an explicit update instead of relying on silent overwrite.
    """


class MappingNotFoundError(RepositoryError):
    """Raised when an explicit mapping update targets a missing row."""
