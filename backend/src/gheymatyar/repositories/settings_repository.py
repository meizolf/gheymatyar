"""Application settings key/value persistence."""

from __future__ import annotations

from sqlalchemy.orm import Session

from gheymatyar.db.models import SettingRow
from gheymatyar.repositories._session import flush_or_rollback
from gheymatyar.repositories.records import SettingRecord


def _to_record(row: SettingRow) -> SettingRecord:
    return SettingRecord(key=row.key, value=row.value)


class SettingsRepository:
    """Simple key/value settings store."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def get(self, key: str) -> SettingRecord | None:
        """Return the setting for ``key``, or ``None`` if it does not exist."""
        row = self._session.get(SettingRow, key)
        return _to_record(row) if row is not None else None

    def set(self, key: str, value: str) -> SettingRecord:
        """Create or update a setting (upsert)."""
        cleaned_key = key.strip()
        if not cleaned_key:
            raise ValueError("setting key must be non-empty")

        row = self._session.get(SettingRow, cleaned_key)
        if row is None:
            row = SettingRow(key=cleaned_key, value=value)
            self._session.add(row)
        else:
            row.value = value

        flush_or_rollback(self._session)
        return _to_record(row)
