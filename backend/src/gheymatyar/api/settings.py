"""Application settings endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from gheymatyar.api.deps import DEFAULT_SETTING_KEYS, get_db_session, get_processing_service
from gheymatyar.api.schemas import SettingsResponse, SettingsUpdateRequest
from gheymatyar.repositories._session import commit_or_raise
from gheymatyar.repositories.settings_repository import SettingsRepository
from gheymatyar.services.price_validation import (
    DECREASE_THRESHOLD_KEY,
    INCREASE_THRESHOLD_KEY,
    parse_warning_percent,
)
from gheymatyar.services.processing import ProcessingService, load_price_thresholds

router = APIRouter(tags=["settings"])

ALLOWED_KEYS = frozenset(DEFAULT_SETTING_KEYS)
THRESHOLD_KEYS = frozenset({INCREASE_THRESHOLD_KEY, DECREASE_THRESHOLD_KEY})


@router.get("/settings", response_model=SettingsResponse)
def read_settings(db: Session = Depends(get_db_session)) -> SettingsResponse:
    thresholds = load_price_thresholds(db)
    return SettingsResponse(
        settings={
            INCREASE_THRESHOLD_KEY: format(thresholds.increase, "f"),
            DECREASE_THRESHOLD_KEY: format(thresholds.decrease, "f"),
        }
    )


@router.put("/settings", response_model=SettingsResponse)
def update_settings(
    body: SettingsUpdateRequest,
    db: Session = Depends(get_db_session),
    service: ProcessingService = Depends(get_processing_service),
) -> SettingsResponse:
    cleaned_values: dict[str, str] = {}
    for key, value in body.settings.items():
        if key not in ALLOWED_KEYS:
            raise HTTPException(status_code=400, detail=f"unknown setting key: {key}")
        cleaned = str(value).strip()
        if not cleaned:
            raise HTTPException(status_code=400, detail=f"empty value for {key}")
        if key in THRESHOLD_KEYS:
            try:
                cleaned = format(parse_warning_percent(cleaned, name=key), "f")
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
        cleaned_values[key] = cleaned
    # Validate everything first, save together, and only then re-check the
    # open sessions: a failed save leaves both the settings and the reviews
    # as they were.
    repo = SettingsRepository(db)
    for key, cleaned in cleaned_values.items():
        repo.set(key, cleaned)
    commit_or_raise(db)
    service.recheck_price_thresholds(db)
    return read_settings(db)
