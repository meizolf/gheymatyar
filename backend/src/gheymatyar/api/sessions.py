"""Processing session and workflow endpoints."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from gheymatyar.api.deps import get_db_session, get_processing_service
from gheymatyar.api.schemas import (
    CandidateResponse,
    CandidatesResponse,
    ConfirmMappingRequest,
    ExportResponse,
    MatchRequest,
    ProductSearchResponse,
    ReviewDecisionRequest,
    SessionCreateResponse,
    SessionSummaryResponse,
    UploadExcelResponse,
    UploadPdfResponse,
)
from gheymatyar.domain.enums import MatchStatus, ReviewDecision
from gheymatyar.services.processing import ProcessingService, candidate_to_dict
from gheymatyar.suppliers.errors import SupplierPdfError, UnsupportedSupplierError

router = APIRouter(tags=["sessions"])


def _summary(service: ProcessingService, session_id: str) -> SessionSummaryResponse:
    session = service.get_session(session_id)
    return SessionSummaryResponse(**service.preview_summary(session))


@router.post("/sessions", response_model=SessionCreateResponse)
def create_session(
    service: ProcessingService = Depends(get_processing_service),
) -> SessionCreateResponse:
    session = service.create_session()
    return SessionCreateResponse(session_id=session.session_id)


@router.get("/sessions/{session_id}", response_model=SessionSummaryResponse)
def get_session(
    session_id: str,
    service: ProcessingService = Depends(get_processing_service),
) -> SessionSummaryResponse:
    try:
        return _summary(service, session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="session not found") from exc


@router.post(
    "/sessions/{session_id}/pioneers-excel",
    response_model=UploadExcelResponse,
)
async def upload_pioneers_excel(
    session_id: str,
    file: UploadFile = File(...),
    service: ProcessingService = Depends(get_processing_service),
) -> UploadExcelResponse:
    name = (file.filename or "").lower()
    if name.endswith(".xlsm") or not (
        name.endswith(".xlsx") or name.endswith(".xls")
    ):
        raise HTTPException(
            status_code=400,
            detail="expected an .xlsx or .xls Excel upload (.xlsm is not supported)",
        )
    try:
        service.upload_pioneers_excel(session_id, file.filename, file.file)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="session not found") from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return UploadExcelResponse(**_summary(service, session_id).model_dump())


@router.post(
    "/sessions/{session_id}/supplier-pdf",
    response_model=UploadPdfResponse,
)
async def upload_supplier_pdf(
    session_id: str,
    supplier_key: str = Form(...),
    file: UploadFile = File(...),
    service: ProcessingService = Depends(get_processing_service),
) -> UploadPdfResponse:
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="expected a .pdf upload")
    try:
        service.upload_supplier_pdf(
            session_id,
            supplier_key=supplier_key,
            filename=file.filename,
            stream=file.file,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="session not found") from exc
    except UnsupportedSupplierError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except SupplierPdfError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return UploadPdfResponse(**_summary(service, session_id).model_dump())


@router.post(
    "/sessions/{session_id}/match",
    response_model=CandidatesResponse,
)
def run_match(
    session_id: str,
    body: MatchRequest | None = None,
    service: ProcessingService = Depends(get_processing_service),
    db: Session = Depends(get_db_session),
) -> CandidatesResponse:
    threshold_override = (
        body.suspicious_percent_threshold if body is not None else None
    )
    try:
        session = service.run_matching(
            session_id, db, suspicious_percent_threshold=threshold_override
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="session not found") from exc
    except UnsupportedSupplierError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return CandidatesResponse(
        session_id=session.session_id,
        matched_count=session.matched_count,
        unmatched_count=session.unmatched_count,
        ambiguous_count=session.ambiguous_count,
        candidates=[
            CandidateResponse(**candidate_to_dict(c)) for c in session.candidates
        ],
    )


@router.get(
    "/sessions/{session_id}/candidates",
    response_model=CandidatesResponse,
)
def list_candidates(
    session_id: str,
    status: str | None = Query(
        default=None, description="Optional MATCHED|UNMATCHED|AMBIGUOUS filter"
    ),
    service: ProcessingService = Depends(get_processing_service),
) -> CandidatesResponse:
    try:
        session = service.get_session(session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="session not found") from exc

    candidates = session.candidates
    if status:
        try:
            wanted = MatchStatus(status.upper())
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="invalid status filter") from exc
        candidates = [c for c in candidates if c.status == wanted]

    return CandidatesResponse(
        session_id=session.session_id,
        matched_count=session.matched_count,
        unmatched_count=session.unmatched_count,
        ambiguous_count=session.ambiguous_count,
        candidates=[CandidateResponse(**candidate_to_dict(c)) for c in candidates],
    )


@router.get(
    "/sessions/{session_id}/preview",
    response_model=CandidatesResponse,
)
def price_preview(
    session_id: str,
    service: ProcessingService = Depends(get_processing_service),
) -> CandidatesResponse:
    """Return matched candidates (price-change preview)."""
    try:
        session = service.get_session(session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="session not found") from exc
    matched = [c for c in session.candidates if c.status == MatchStatus.MATCHED]
    return CandidatesResponse(
        session_id=session.session_id,
        matched_count=session.matched_count,
        unmatched_count=session.unmatched_count,
        ambiguous_count=session.ambiguous_count,
        candidates=[CandidateResponse(**candidate_to_dict(c)) for c in matched],
    )


@router.get(
    "/sessions/{session_id}/pioneers-products/search",
    response_model=ProductSearchResponse,
)
def search_products(
    session_id: str,
    q: str = Query(..., min_length=1),
    limit: int = Query(25, ge=1, le=100),
    service: ProcessingService = Depends(get_processing_service),
) -> ProductSearchResponse:
    try:
        results = service.search_products(session_id, q, limit=limit)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="session not found") from exc
    return ProductSearchResponse(results=results)


@router.post(
    "/sessions/{session_id}/candidates/{candidate_id}/confirm-mapping",
    response_model=CandidateResponse,
)
def confirm_mapping(
    session_id: str,
    candidate_id: str,
    body: ConfirmMappingRequest,
    service: ProcessingService = Depends(get_processing_service),
    db: Session = Depends(get_db_session),
) -> CandidateResponse:
    try:
        updated = service.confirm_mapping(
            session_id,
            db,
            candidate_id=candidate_id,
            pioneers_row_number=body.pioneers_row_number,
            save=body.save,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="session or candidate not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return CandidateResponse(**candidate_to_dict(updated))


@router.post(
    "/sessions/{session_id}/candidates/{candidate_id}/review",
    response_model=CandidateResponse,
)
def set_review(
    session_id: str,
    candidate_id: str,
    body: ReviewDecisionRequest,
    service: ProcessingService = Depends(get_processing_service),
) -> CandidateResponse:
    try:
        decision = ReviewDecision(body.decision.upper())
    except ValueError as exc:
        raise HTTPException(
            status_code=400, detail="decision must be INCLUDE, EXCLUDE, or APPROVE"
        ) from exc
    try:
        updated = service.set_review_decision(
            session_id, candidate_id=candidate_id, decision=decision
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="session or candidate not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return CandidateResponse(**candidate_to_dict(updated))


@router.post(
    "/sessions/{session_id}/export",
    response_model=ExportResponse,
)
def export_excel(
    session_id: str,
    service: ProcessingService = Depends(get_processing_service),
    db: Session = Depends(get_db_session),
) -> ExportResponse:
    try:
        result = service.export_excel(session_id, db)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="session not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ExportResponse(
        session_id=session_id,
        output_filename=Path(result.output_path).name,
        updated_count=result.updated_count,
        download_path=f"/api/sessions/{session_id}/download",
    )


@router.get("/sessions/{session_id}/download")
def download_excel(
    session_id: str,
    service: ProcessingService = Depends(get_processing_service),
) -> FileResponse:
    try:
        session = service.get_session(session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="session not found") from exc
    if session.output_path is None or not session.output_path.is_file():
        raise HTTPException(status_code=404, detail="export not available; run export first")
    download_name = "pioneers_updated.xlsx"
    if session.pioneers_filename:
        stem = Path(session.pioneers_filename).stem
        download_name = f"{stem}_updated.xlsx"
    return FileResponse(
        path=session.output_path,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=download_name,
    )
