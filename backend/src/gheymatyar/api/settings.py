"""Application settings endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from gheymatyar.api.deps import DEFAULT_SETTING_KEYS, get_db_session
from gheymatyar.api.schemas import SettingsResponse, SettingsUpdateRequest
from gheymatyar.repositories.settings_repository import SettingsRepository
from gheymatyar.services.price_validation import parse_suspicious_percent_threshold

router = APIRouter(tags=["settings"])

ALLOWED_KEYS = frozenset(DEFAULT_SETTING_KEYS)
THRESHOLD_KEY = "suspicious_percent_threshold"


@router.get("/settings", response_model=SettingsResponse)
def read_settings(db: Session = Depends(get_db_session)) -> SettingsResponse:
    repo = SettingsRepository(db)
    values = dict(DEFAULT_SETTING_KEYS)
    for key in ALLOWED_KEYS:
        row = repo.get(key)
        if row is not None:
            values[key] = row.value
    return SettingsResponse(settings=values)


@router.put("/settings", response_model=SettingsResponse)
def update_settings(
    body: SettingsUpdateRequest,
    db: Session = Depends(get_db_session),
) -> SettingsResponse:
    repo = SettingsRepository(db)
    for key, value in body.settings.items():
        if key not in ALLOWED_KEYS:
            raise HTTPException(status_code=400, detail=f"unknown setting key: {key}")
        cleaned = str(value).strip()
        if not cleaned:
            raise HTTPException(status_code=400, detail=f"empty value for {key}")
        if key == THRESHOLD_KEY:
            try:
                parsed = parse_suspicious_percent_threshold(cleaned)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            cleaned = format(parsed, "f")
        repo.set(key, cleaned)
    return read_settings(db)
