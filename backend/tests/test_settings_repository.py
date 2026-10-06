"""SettingsRepository tests."""

from __future__ import annotations

from sqlalchemy.orm import Session

from gheymatyar.repositories import SettingsRepository


def test_missing_setting_returns_none(session: Session) -> None:
    repo = SettingsRepository(session)
    assert repo.get("does.not.exist") is None


def test_create_and_retrieve_setting(session: Session) -> None:
    repo = SettingsRepository(session)
    created = repo.set("theme", "light")
    assert created.key == "theme"
    assert created.value == "light"

    fetched = repo.get("theme")
    assert fetched is not None
    assert fetched.value == "light"


def test_update_existing_setting(session: Session) -> None:
    repo = SettingsRepository(session)
    repo.set("locale", "en")
    updated = repo.set("locale", "fa")

    assert updated.value == "fa"
    assert repo.get("locale") is not None
    assert repo.get("locale").value == "fa"  # type: ignore[union-attr]
