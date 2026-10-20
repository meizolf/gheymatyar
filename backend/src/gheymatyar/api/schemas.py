"""Pydantic request/response models for the HTTP API."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class HealthResponse(BaseModel):
    status: str


class SupplierInfoResponse(BaseModel):
    key: str
    display_name: str


class SessionCreateResponse(BaseModel):
    session_id: str


class InvalidRowResponse(BaseModel):
    row_number: int
    column: str | None = None
    reason: str
    code: str | None = None
    name: str | None = None


class SessionSummaryResponse(BaseModel):
    session_id: str
    supplier_key: str | None = None
    supplier_display_name: str | None = None
    pioneers_filename: str | None = None
    pdf_filename: str | None = None
    product_count: int = 0
    invalid_row_count: int = 0
    invalid_rows: list[InvalidRowResponse] = Field(default_factory=list)
    duplicate_codes: dict[str, list[int]] = Field(default_factory=dict)
    supplier_item_count: int = 0
    matched_count: int = 0
    unmatched_count: int = 0
    ambiguous_count: int = 0
    warning_count: int = 0
    exportable_count: int = 0
    parse_warnings: list[str] = Field(default_factory=list)
    export_available: bool = False


class UploadExcelResponse(SessionSummaryResponse):
    pass


class UploadPdfResponse(SessionSummaryResponse):
    pass


class MatchRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    suspicious_percent_threshold: str | None = Field(
        default=None,
        description="Absolute percent threshold for suspicious price changes (default 30)",
    )


class CandidateResponse(BaseModel):
    candidate_id: str
    row_number: int | None = None
    pioneers_code: str | None = None
    pioneers_name: str | None = None
    supplier_code: str | None = None
    supplier_name: str
    old_price: str | None = None
    new_price: str | None = None
    absolute_change: str | None = None
    percentage_change: str | None = None
    match_type: str | None = None
    status: str
    review_decision: str
    warnings: list[str] = Field(default_factory=list)
    suggestions: list[dict[str, Any]] = Field(default_factory=list)
    exportable: bool = False
    supplier_name_normalized: str | None = None


class CandidatesResponse(BaseModel):
    session_id: str
    matched_count: int
    unmatched_count: int
    ambiguous_count: int
    candidates: list[CandidateResponse]


class ConfirmMappingRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    pioneers_row_number: int = Field(..., ge=2)
    save: bool = True


class ReviewDecisionRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    decision: str = Field(..., description="INCLUDE | EXCLUDE | APPROVE")


class ProductSearchResponse(BaseModel):
    results: list[dict[str, Any]]


class ExportResponse(BaseModel):
    session_id: str
    output_filename: str
    updated_count: int
    download_path: str


class SettingItem(BaseModel):
    key: str
    value: str


class SettingsResponse(BaseModel):
    settings: dict[str, str]


class SettingsUpdateRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    settings: dict[str, str]


class ErrorResponse(BaseModel):
    detail: str


class MappingResponse(BaseModel):
    id: int
    supplier_key: str
    supplier_name_raw: str
    supplier_name_normalized: str
    pioneers_name_raw: str
    pioneers_name_normalized: str
    pioneers_code: str | None = None
    mapping_type: str
    created_at: str
    updated_at: str


class MappingsListResponse(BaseModel):
    supplier_key: str
    mappings: list[MappingResponse]


class MappingUpdateRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    pioneers_name_raw: str = Field(..., min_length=1)
    pioneers_code: str | None = None
