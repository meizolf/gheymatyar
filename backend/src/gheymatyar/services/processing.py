"""Orchestrates the Excel + PDF → matched preview → export workflow."""

from __future__ import annotations

import re
from decimal import Decimal
from pathlib import Path
from typing import BinaryIO
from uuid import uuid4

from sqlalchemy.orm import Session

from gheymatyar.domain.enums import MappingType, MatchStatus, ReviewDecision
from gheymatyar.domain.update_candidate import UpdateCandidate
from gheymatyar.parsers.pioneers_excel_parser import PioneersExcelParser
from gheymatyar.parsers.pioneers_html_xls import convert_pioneers_html_xls_to_xlsx
from gheymatyar.parsers.workbook_format import (
    WorkbookFormat,
    detect_workbook_format,
    unsupported_format_message,
)
from gheymatyar.repositories.mapping_repository import MappingRepository
from gheymatyar.repositories.settings_repository import SettingsRepository
from gheymatyar.repositories.supplier_repository import SupplierRepository
from gheymatyar.services.matching import (
    SavedNameMapping,
    match_supplier_items,
    search_pioneers_products,
)
from gheymatyar.services.name_normalization import normalize_product_name
from gheymatyar.services.pioneers_excel_writer import (
    ExcelUpdateResult,
    update_final_sale_prices,
)
from gheymatyar.services.price_validation import (
    DEFAULT_SUSPICIOUS_PERCENT_THRESHOLD,
    IDENTITY_CONFLICT_WARNING,
    apply_price_warnings,
    is_exportable,
    resolve_suspicious_percent_threshold,
    to_final_sale_updates,
)
from gheymatyar.services.session_store import ProcessingSession, SessionStore
from gheymatyar.suppliers.registry import SupplierProcessorRegistry, get_default_registry

_SAFE_FILENAME_RE = re.compile(r"[^\w.\-()+ \u0600-\u06FF]+", re.UNICODE)
SETTING_THRESHOLD_KEY = "suspicious_percent_threshold"


def _safe_filename(name: str, *, default: str) -> str:
    base = Path(name).name.strip() or default
    cleaned = _SAFE_FILENAME_RE.sub("_", base).strip("._") or default
    return cleaned[:180]


def _invalidate_export(session: ProcessingSession) -> None:
    """Drop any previously generated workbook so downloads cannot be stale."""
    if session.output_path is not None:
        try:
            if session.output_path.is_file():
                session.output_path.unlink()
        except OSError:
            pass
    session.output_path = None


class ProcessingService:
    """Application service used by API controllers."""

    def __init__(
        self,
        store: SessionStore,
        *,
        registry: SupplierProcessorRegistry | None = None,
        parser: PioneersExcelParser | None = None,
    ) -> None:
        self._store = store
        self._registry = registry or get_default_registry()
        self._parser = parser or PioneersExcelParser()

    def create_session(self) -> ProcessingSession:
        return self._store.create()

    def get_session(self, session_id: str) -> ProcessingSession:
        return self._store.require(session_id)

    def list_suppliers(self) -> list[dict[str, str]]:
        return [
            {"key": info.key, "display_name": info.display_name}
            for info in self._registry.list_suppliers()
        ]

    def upload_pioneers_excel(
        self, session_id: str, filename: str, stream: BinaryIO
    ) -> ProcessingSession:
        with self._store.session_lock(session_id):
            session = self._store.require(session_id)
            assert session.work_dir is not None
            safe_name = _safe_filename(filename, default="pioneers.xlsx")
            lower = safe_name.lower()
            if lower.endswith(".xlsm"):
                raise ValueError(
                    "expected an .xlsx or .xls Excel upload (.xlsm is not supported)"
                )
            if not (lower.endswith(".xlsx") or lower.endswith(".xls")):
                raise ValueError(
                    "expected an .xlsx or .xls Excel upload (.xlsm is not supported)"
                )

            raw = stream.read()
            fmt = detect_workbook_format(raw)
            upload_suffix = ".xls" if lower.endswith(".xls") else ".xlsx"
            token = uuid4().hex
            upload_staging = (
                session.work_dir / f"pioneers.upload.{token}{upload_suffix}"
            )
            # Build the replacement workbook beside the current one so a failed
            # re-upload never destroys the previously accepted file.
            candidate = session.work_dir / f"pioneers.candidate.{token}.xlsx"
            final = session.work_dir / "pioneers.xlsx"
            upload_staging.write_bytes(raw)
            try:
                if fmt == WorkbookFormat.XLSX:
                    if not lower.endswith(".xlsx"):
                        raise ValueError(
                            "file contents are .xlsx but the filename extension is not .xlsx"
                        )
                    upload_staging.replace(candidate)
                elif fmt == WorkbookFormat.PIONEERS_HTML_XLS:
                    convert_pioneers_html_xls_to_xlsx(upload_staging, candidate)
                    upload_staging.unlink(missing_ok=True)
                else:
                    raise ValueError(unsupported_format_message(raw))

                parse_result = self._parser.parse(candidate)
            except Exception:
                upload_staging.unlink(missing_ok=True)
                candidate.unlink(missing_ok=True)
                raise

            candidate.replace(final)
            session.pioneers_filename = safe_name
            session.pioneers_path = final
            session.products = list(parse_result.products)
            session.invalid_rows = list(parse_result.invalid_rows)
            session.duplicate_codes = dict(parse_result.duplicate_codes)
            session.candidates = []
            session.matched_count = 0
            session.unmatched_count = 0
            session.ambiguous_count = 0
            _invalidate_export(session)
            return session

    def upload_supplier_pdf(
        self,
        session_id: str,
        *,
        supplier_key: str,
        filename: str,
        stream: BinaryIO,
    ) -> ProcessingSession:
        with self._store.session_lock(session_id):
            session = self._store.require(session_id)
            assert session.work_dir is not None
            processor = self._registry.get(supplier_key)
            safe_name = _safe_filename(filename, default="supplier.pdf")

            staging = session.work_dir / f"supplier.staging.{uuid4().hex}.pdf"
            staging.write_bytes(stream.read())
            try:
                parse_result = processor.parse_pdf(staging)
            except Exception:
                staging.unlink(missing_ok=True)
                raise

            final = session.work_dir / "supplier.pdf"
            staging.replace(final)

            session.supplier_key = processor.supplier_key
            session.supplier_display_name = processor.display_name
            session.pdf_filename = safe_name
            session.pdf_path = final
            session.supplier_items = list(parse_result.items)
            session.parse_warnings = list(parse_result.warnings)
            session.metadata["supplier_parse"] = parse_result.source_metadata
            session.candidates = []
            session.matched_count = 0
            session.unmatched_count = 0
            session.ambiguous_count = 0
            _invalidate_export(session)
            return session

    def run_matching(
        self,
        session_id: str,
        db_session: Session,
        *,
        suspicious_percent_threshold: str | None = None,
    ) -> ProcessingSession:
        with self._store.session_lock(session_id):
            return self._run_matching_unlocked(
                session_id,
                db_session,
                suspicious_percent_threshold=suspicious_percent_threshold,
            )

    def _run_matching_unlocked(
        self,
        session_id: str,
        db_session: Session,
        *,
        suspicious_percent_threshold: str | None = None,
    ) -> ProcessingSession:
        session = self._store.require(session_id)
        if not session.products:
            raise ValueError("Pioneers Excel has not been uploaded")
        if not session.supplier_items or not session.supplier_key:
            raise ValueError("Supplier PDF has not been uploaded")

        processor = self._registry.get(session.supplier_key)
        supplier_row = self._ensure_supplier_row(db_session, processor)
        mapping_repo = MappingRepository(db_session)
        saved = [
            SavedNameMapping(
                supplier_name_normalized=row.supplier_name_normalized,
                pioneers_name_raw=row.pioneers_name_raw,
                pioneers_name_normalized=row.pioneers_name_normalized,
                pioneers_code=row.pioneers_code,
            )
            for row in mapping_repo.list_for_supplier(supplier_row.id)
        ]

        match_result = match_supplier_items(
            session.supplier_items,
            session.products,
            processor=processor,
            saved_mappings=saved,
        )

        saved_setting = SettingsRepository(db_session).get(SETTING_THRESHOLD_KEY)
        threshold = resolve_suspicious_percent_threshold(
            request_value=suspicious_percent_threshold,
            saved_value=saved_setting.value if saved_setting else None,
            default=DEFAULT_SUSPICIOUS_PERCENT_THRESHOLD,
        )
        session.candidates = apply_price_warnings(
            match_result.candidates,
            suspicious_percent_threshold=threshold,
            conflicted_row_numbers=session.conflicted_row_numbers,
        )
        session.matched_count = match_result.matched_count
        session.unmatched_count = match_result.unmatched_count
        session.ambiguous_count = match_result.ambiguous_count
        session.metadata["suspicious_percent_threshold"] = str(threshold)
        _invalidate_export(session)
        return session

    def search_products(
        self, session_id: str, query: str, *, limit: int = 25
    ) -> list[dict[str, object]]:
        session = self._store.require(session_id)
        products = search_pioneers_products(session.products, query, limit=limit)
        return [
            {
                "row_number": p.row_number,
                "code": p.code,
                "name": p.name,
                "sale_price": str(p.sale_price) if p.sale_price is not None else None,
            }
            for p in products
        ]

    def confirm_mapping(
        self,
        session_id: str,
        db_session: Session,
        *,
        candidate_id: str,
        pioneers_row_number: int,
        save: bool = True,
    ) -> UpdateCandidate:
        with self._store.session_lock(session_id):
            session = self._store.require(session_id)
            candidate = session.get_candidate(candidate_id)
            if candidate is None:
                raise KeyError(candidate_id)

            product = next(
                (p for p in session.products if p.row_number == pioneers_row_number),
                None,
            )
            if product is None:
                raise ValueError(f"no Pioneers product at row {pioneers_row_number}")

            if not session.supplier_key:
                raise ValueError("supplier is not set on this session")
            processor = self._registry.get(session.supplier_key)
            new_price = candidate.new_price
            if new_price is None:
                raise ValueError("candidate has no new price")

            absolute = (
                new_price - product.sale_price
                if product.sale_price is not None
                else None
            )
            percentage = None
            if (
                product.sale_price is not None
                and product.sale_price != Decimal("0")
                and absolute is not None
            ):
                percentage = (absolute / product.sale_price) * Decimal("100")

            updated = UpdateCandidate(
                candidate_id=candidate.candidate_id,
                row_number=product.row_number,
                pioneers_code=product.code,
                pioneers_name=product.name,
                supplier_code=candidate.supplier_code,
                supplier_name=candidate.supplier_name,
                old_price=product.sale_price,
                new_price=new_price,
                absolute_change=absolute,
                percentage_change=percentage,
                match_type=MappingType.MANUAL,
                status=MatchStatus.MATCHED,
                review_decision=ReviewDecision.INCLUDE,
                warnings=[],
                suggestions=[],
            )
            threshold = resolve_suspicious_percent_threshold(
                request_value=session.metadata.get("suspicious_percent_threshold"),
                default=DEFAULT_SUSPICIOUS_PERCENT_THRESHOLD,
            )
            updated = apply_price_warnings(
                [updated],
                suspicious_percent_threshold=threshold,
                conflicted_row_numbers=session.conflicted_row_numbers,
            )[0]
            session.replace_candidate(updated)
            self._recount(session)
            _invalidate_export(session)

            if save:
                supplier_row = self._ensure_supplier_row(db_session, processor)
                MappingRepository(db_session).upsert(
                    supplier_id=supplier_row.id,
                    supplier_name_raw=candidate.supplier_name,
                    pioneers_name_raw=product.name,
                    pioneers_code=product.code,
                    mapping_type=MappingType.MANUAL,
                )
            return updated

    def set_review_decision(
        self,
        session_id: str,
        *,
        candidate_id: str,
        decision: ReviewDecision,
    ) -> UpdateCandidate:
        with self._store.session_lock(session_id):
            session = self._store.require(session_id)
            candidate = session.get_candidate(candidate_id)
            if candidate is None:
                raise KeyError(candidate_id)
            if (
                candidate.status != MatchStatus.MATCHED
                and decision != ReviewDecision.EXCLUDE
            ):
                raise ValueError("only matched candidates can be included or approved")
            if (
                decision == ReviewDecision.APPROVE
                and IDENTITY_CONFLICT_WARNING in candidate.warnings
            ):
                raise ValueError(
                    "cannot approve a candidate with a duplicate Pioneers product code"
                )
            updated = candidate.model_copy(update={"review_decision": decision})
            session.replace_candidate(updated)
            _invalidate_export(session)
            return updated

    def export_excel(self, session_id: str) -> ExcelUpdateResult:
        with self._store.session_lock(session_id):
            session = self._store.require(session_id)
            if session.pioneers_path is None or not session.pioneers_path.is_file():
                raise ValueError("Pioneers Excel has not been uploaded")
            assert session.work_dir is not None

            # Snapshot decisions under the same lock that review mutations use.
            guarded = apply_price_warnings(
                session.candidates,
                suspicious_percent_threshold=resolve_suspicious_percent_threshold(
                    request_value=session.metadata.get("suspicious_percent_threshold"),
                    default=DEFAULT_SUSPICIOUS_PERCENT_THRESHOLD,
                ),
                conflicted_row_numbers=session.conflicted_row_numbers,
            )
            session.candidates = guarded

            updates = to_final_sale_updates(session.candidates)
            if not updates:
                raise ValueError("no approved updates available for export")

            output = session.work_dir / "pioneers_updated.xlsx"
            if output.exists():
                output.unlink()
            result = update_final_sale_prices(session.pioneers_path, output, updates)
            session.output_path = output
            return result

    def preview_summary(self, session: ProcessingSession) -> dict[str, object]:
        exportable = sum(1 for c in session.candidates if is_exportable(c))
        warned = sum(1 for c in session.candidates if c.warnings)
        return {
            "session_id": session.session_id,
            "supplier_key": session.supplier_key,
            "supplier_display_name": session.supplier_display_name,
            "pioneers_filename": session.pioneers_filename,
            "pdf_filename": session.pdf_filename,
            "product_count": len(session.products),
            "invalid_row_count": len(session.invalid_rows),
            "invalid_rows": [
                {
                    "row_number": row.row_number,
                    "column": row.column,
                    "reason": row.reason,
                    "code": row.code,
                    "name": row.name,
                }
                for row in session.invalid_rows
            ],
            "duplicate_codes": {
                code: list(rows) for code, rows in session.duplicate_codes.items()
            },
            "supplier_item_count": len(session.supplier_items),
            "matched_count": session.matched_count,
            "unmatched_count": session.unmatched_count,
            "ambiguous_count": session.ambiguous_count,
            "warning_count": warned,
            "exportable_count": exportable,
            "parse_warnings": session.parse_warnings,
            "export_available": bool(
                session.output_path and session.output_path.is_file()
            ),
        }

    @staticmethod
    def _ensure_supplier_row(db_session: Session, processor) -> object:
        repo = SupplierRepository(db_session)
        existing = repo.get_by_name(processor.display_name)
        if existing is not None:
            return existing
        for row in repo.list_all():
            if row.parser_type == processor.supplier_key:
                return row
        return repo.create(
            name=processor.display_name, parser_type=processor.supplier_key
        )

    @staticmethod
    def _recount(session: ProcessingSession) -> None:
        session.matched_count = sum(
            1 for c in session.candidates if c.status == MatchStatus.MATCHED
        )
        session.unmatched_count = sum(
            1 for c in session.candidates if c.status == MatchStatus.UNMATCHED
        )
        session.ambiguous_count = sum(
            1 for c in session.candidates if c.status == MatchStatus.AMBIGUOUS
        )


def candidate_to_dict(candidate: UpdateCandidate) -> dict[str, object]:
    return {
        "candidate_id": candidate.candidate_id,
        "row_number": candidate.row_number,
        "pioneers_code": candidate.pioneers_code,
        "pioneers_name": candidate.pioneers_name,
        "supplier_code": candidate.supplier_code,
        "supplier_name": candidate.supplier_name,
        "old_price": str(candidate.old_price)
        if candidate.old_price is not None
        else None,
        "new_price": str(candidate.new_price)
        if candidate.new_price is not None
        else None,
        "absolute_change": str(candidate.absolute_change)
        if candidate.absolute_change is not None
        else None,
        "percentage_change": str(candidate.percentage_change)
        if candidate.percentage_change is not None
        else None,
        "match_type": candidate.match_type.value if candidate.match_type else None,
        "status": candidate.status.value,
        "review_decision": candidate.review_decision.value,
        "warnings": list(candidate.warnings),
        "suggestions": list(candidate.suggestions),
        "exportable": is_exportable(candidate),
        "supplier_name_normalized": normalize_product_name(candidate.supplier_name),
    }
