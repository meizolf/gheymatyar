"""Supported supplier listing."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from gheymatyar.api.deps import get_processing_service
from gheymatyar.api.schemas import SupplierInfoResponse
from gheymatyar.services.processing import ProcessingService

router = APIRouter(tags=["suppliers"])


@router.get("/suppliers", response_model=list[SupplierInfoResponse])
def list_suppliers(
    service: ProcessingService = Depends(get_processing_service),
) -> list[SupplierInfoResponse]:
    return [SupplierInfoResponse(**item) for item in service.list_suppliers()]
