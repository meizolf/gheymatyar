"""Repository layer: persist and retrieve data without business logic.

Repositories accept a SQLAlchemy ``Session`` owned by the caller. They flush
writes so constraint errors surface immediately, roll the session back on
integrity failures, and return plain dataclasses — never ORM instances.
"""

from gheymatyar.repositories.exceptions import (
    MappingConflictError,
    MappingNotFoundError,
    RepositoryError,
)
from gheymatyar.repositories.job_repository import JobRepository
from gheymatyar.repositories.mapping_repository import MappingRepository
from gheymatyar.repositories.records import (
    JobItemRecord,
    JobRecord,
    ProductMappingRecord,
    SettingRecord,
    SupplierRecord,
)
from gheymatyar.repositories.settings_repository import SettingsRepository
from gheymatyar.repositories.supplier_repository import SupplierRepository

__all__ = [
    "JobItemRecord",
    "JobRecord",
    "JobRepository",
    "MappingConflictError",
    "MappingNotFoundError",
    "MappingRepository",
    "ProductMappingRecord",
    "RepositoryError",
    "SettingRecord",
    "SettingsRepository",
    "SupplierRecord",
    "SupplierRepository",
]
