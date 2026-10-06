"""SQLite persistence infrastructure (SQLAlchemy 2.x).

ORM models and engine/session helpers live here. Domain models in
``gheymatyar.domain`` remain independent of SQLAlchemy.
"""

from gheymatyar.db.database import (
    Database,
    create_engine_for_url,
    create_session_factory,
    init_db,
    session_scope,
)
from gheymatyar.db.models import (
    Base,
    JobItemRow,
    JobRow,
    JobStatus,
    ProductMappingRow,
    SettingRow,
    SupplierRow,
)

__all__ = [
    "Base",
    "Database",
    "JobItemRow",
    "JobRow",
    "JobStatus",
    "ProductMappingRow",
    "SettingRow",
    "SupplierRow",
    "create_engine_for_url",
    "create_session_factory",
    "init_db",
    "session_scope",
]
