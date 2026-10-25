"""Orchestrates the Excel + PDF → matched preview → export workflow."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
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
from gheymatyar.repositories._session import commit_or_raise
from gheymatyar.repositories.mapping_repository import MappingRepository
from gheymatyar.repositories.product_decision_repository import ProductDecisionRepository
from gheymatyar.repositories.records import ProductMappingRecord, SupplierRecord
from gheymatyar.repositories.settings_repository import SettingsRepository
from gheymatyar.repositories.supplier_repository import SupplierRepository
from gheymatyar.services.matching import (
    SavedNameMapping,
    item_decision_identities,
    match_supplier_items,
    search_pioneers_products,
)
from gheymatyar.services.name_normalization import normalize_product_name
from gheymatyar.services.product_identity import supplier_product_identity
from gheymatyar.services.pioneers_excel_writer import (
    ExcelUpdateResult,
    update_final_sale_prices,
)
from gheymatyar.services.pioneers_legacy_xls_writer import write_pioneers_legacy_xls
from gheymatyar.services.price_validation import (
    DEFAULT_SUSPICIOUS_PERCENT_THRESHOLD,
    IDENTITY_CONFLICT_WARNING,
    apply_price_warnings,
    apply_sale_compatibility,
    assemble_export_updates,
    is_exportable,
    resolve_suspicious_percent_threshold,
)
from gheymatyar.services.session_store import ProcessingSession, SessionStore
from gheymatyar.suppliers.errors import UnsupportedSupplierError
from gheymatyar.suppliers.registry import SupplierProcessorRegistry, get_default_registry

_SAFE_FILENAME_RE = re.compile(r"[^\w.\-()+ \u0600-\u06FF]+", re.UNICODE)
SETTING_THRESHOLD_KEY = "suspicious_percent_threshold"


def _refresh_sale_compatibility(session: ProcessingSession) -> list[UpdateCandidate]:
    """Re-apply the fixed Rial sale rules. There is no currency or basis setting."""
    by_row = {product.row_number: product for product in session.products}
    refreshed: list[UpdateCandidate] = []
    for candidate in session.candidates:
        product = by_row.get(candidate.row_number) if candidate.row_number else None
        if candidate.status == MatchStatus.MATCHED and product is not None:
            candidate = apply_sale_compatibility(
                candidate,
                target_unit=product.unit,
            )
        refreshed.append(candidate)
    return refreshed


def _safe_filename(name: str, *, default: str) -> str:
    base = Path(name).name.strip() or default
    cleaned = _SAFE_FILENAME_RE.sub("_", base).strip("._") or default
    return cleaned[:180]


_EXPORT_FINGERPRINT_KEY = "export_decision_fingerprint"
_EXPORT_ROW_COUNT_KEY = "export_row_count"
_EXPORT_SHA_KEY = "export_content_sha256"
_EXPORT_LEGACY_SHA_KEY = "export_legacy_content_sha256"

#: Excel 97–2003 (BIFF8) ``.xls``, which Pioneers imports. It rejects ``.xlsx``.
EXPORT_FORMAT_XLS = "xls"
#: The verified OpenXML workbook the ``.xls`` is rendered from.
EXPORT_FORMAT_XLSX = "xlsx"
EXPORT_FORMATS = (EXPORT_FORMAT_XLS, EXPORT_FORMAT_XLSX)
DEFAULT_EXPORT_FORMAT = EXPORT_FORMAT_XLS
EXPORT_MEDIA_TYPES = {
    EXPORT_FORMAT_XLS: "application/vnd.ms-excel",
    EXPORT_FORMAT_XLSX: (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    ),
}


@dataclass(frozen=True)
class ExportedFile:
    """One downloadable export file and the hash its download must carry."""

    format: str
    filename: str
    content_sha256: str
    exported_row_count: int
# Persisted mapping token for each session-only or manual override, keyed by
# supplier-product identity. An unrelated ignore must not refresh these.
_MANUAL_BASIS_KEY = "manual_override_basis"
_MAPPING_ABSENT = "absent"


class _DecisionsChanged(Exception):
    """SQLite ignore or mapping state changed while a workbook was written."""


def workbook_decision_stamp(
    db_fingerprint: str, candidates: list[UpdateCandidate]
) -> str:
    """Hash the SQLite decisions together with the rows this export writes.

    A workbook is fresh only when both match. Stamping the database hash alone
    would treat a file built from obsolete targets as current.
    """
    applied: list[list[object]] = []
    for candidate in candidates:
        if is_exportable(candidate):
            applied.append(
                [
                    candidate.row_number,
                    str(candidate.new_price),
                    candidate.supplier_code or "",
                    candidate.pioneers_code or "",
                ]
            )
    applied.sort(key=lambda item: (item[0] is None, item[0], item[2], item[3]))
    payload = json.dumps(
        {"decisions": db_fingerprint, "applied": applied},
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def decision_fingerprint(db_session: Session, supplier_id: int) -> str:
    """Hash the supplier decisions that decide which prices an export may write."""
    ignored = sorted(
        ProductDecisionRepository(db_session).ignored_identity_keys(supplier_id)
    )
    mappings = []
    for row in MappingRepository(db_session).list_for_supplier(supplier_id):
        updated = row.updated_at.isoformat() if row.updated_at else ""
        mappings.append(
            (
                row.identity_key,
                bool(row.legacy_unscoped),
                row.pioneers_name_normalized,
                row.pioneers_code or "",
                updated,
            )
        )
    mappings.sort()
    payload = json.dumps(
        {"ignored": ignored, "mappings": mappings},
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def _require_export_format(fmt: str) -> str:
    if fmt not in EXPORT_FORMATS:
        raise ValueError(
            f"unsupported export format {fmt!r}; expected one of {', '.join(EXPORT_FORMATS)}"
        )
    return fmt


def _download_name(session: ProcessingSession, fmt: str = DEFAULT_EXPORT_FORMAT) -> str:
    stem = (
        Path(session.pioneers_filename).stem
        if session.pioneers_filename
        else "pioneers"
    )
    return f"{stem}_updated.{fmt}"


def _export_path(session: ProcessingSession, fmt: str) -> Path | None:
    if fmt == EXPORT_FORMAT_XLS:
        return session.legacy_output_path
    return session.output_path


def _export_available(session: ProcessingSession, fmt: str) -> bool:
    path = _export_path(session, fmt)
    return path is not None and path.is_file()


def _invalidate_export(session: ProcessingSession) -> None:
    """Drop any previously generated workbooks so downloads cannot be stale."""
    for path in (session.output_path, session.legacy_output_path):
        if path is None:
            continue
        try:
            if path.is_file():
                path.unlink()
        except OSError:
            pass
    session.output_path = None
    session.legacy_output_path = None
    session.metadata.pop(_EXPORT_ROW_COUNT_KEY, None)
    session.metadata.pop(_EXPORT_SHA_KEY, None)
    session.metadata.pop(_EXPORT_LEGACY_SHA_KEY, None)


def _bound_export(
    session: ProcessingSession, data: bytes, fmt: str = DEFAULT_EXPORT_FORMAT
) -> tuple[bytes, str, int, str] | None:
    """Return download bytes only when their hash and row count are the recorded export."""
    sha_key = _EXPORT_LEGACY_SHA_KEY if fmt == EXPORT_FORMAT_XLS else _EXPORT_SHA_KEY
    recorded_sha = session.metadata.get(sha_key)
    recorded_count = session.metadata.get(_EXPORT_ROW_COUNT_KEY)
    digest = hashlib.sha256(data).hexdigest()
    if (
        not isinstance(recorded_sha, str)
        or not isinstance(recorded_count, int)
        or digest != recorded_sha
    ):
        return None
    return data, _download_name(session, fmt), recorded_count, digest


def _clear_match_state(session: ProcessingSession) -> None:
    session.candidates = []
    session.matched_count = 0
    session.unmatched_count = 0
    session.ambiguous_count = 0
    session.ignored_count = 0


def _candidate_identity(processor, candidate: UpdateCandidate) -> str:
    return supplier_product_identity(
        normalized_name=processor.normalize_supplier_name(candidate.supplier_name),
        supplier_code=candidate.supplier_code,
        unit=candidate.source_unit,
    )


def _decision_names(processor, session: ProcessingSession, candidate: UpdateCandidate) -> list[str]:
    """Current normalized name plus prior names of this same code and unit."""
    names = [processor.normalize_supplier_name(candidate.supplier_name)]
    for item in session.supplier_items:
        if item.supplier_name != candidate.supplier_name:
            continue
        if (item.supplier_code or None) != (candidate.supplier_code or None):
            continue
        if (item.unit or None) != (candidate.source_unit or None):
            continue
        for name in processor.prior_normalized_names(item):
            if name and name not in names:
                names.append(name)
        break
    return names


def _candidate_decision_identities(
    processor, session: ProcessingSession, candidate: UpdateCandidate
) -> list[str]:
    for item in session.supplier_items:
        if item.supplier_name != candidate.supplier_name:
            continue
        if (item.supplier_code or None) != (candidate.supplier_code or None):
            continue
        if (item.unit or None) != (candidate.source_unit or None):
            continue
        return item_decision_identities(processor, item)
    return [_candidate_identity(processor, candidate)]


def _mapping_basis_token(record: ProductMappingRecord | None) -> str:
    """Identity of one saved mapping. ``absent`` means no scoped row exists."""
    if record is None:
        return _MAPPING_ABSENT
    return json.dumps(
        {
            "code": record.pioneers_code or "",
            "name": record.pioneers_name_normalized,
            "legacy": bool(record.legacy_unscoped),
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _as_ignored(candidate: UpdateCandidate) -> UpdateCandidate:
    if (
        candidate.status is MatchStatus.IGNORED
        and candidate.review_decision is ReviewDecision.EXCLUDE
    ):
        return candidate
    return candidate.model_copy(
        update={
            "status": MatchStatus.IGNORED,
            "review_decision": ReviewDecision.EXCLUDE,
        }
    )


IGNORED_PRODUCT_MESSAGE = (
    "ignored supplier products must be restored before they can be included or approved"
)


def _revoke_supplier_confirmation(session: ProcessingSession) -> None:
    """Drop parsed prices, matches, and exports after a failed/retracted confirm."""
    session.supplier_confirmed = False
    session.supplier_items = []
    session.parse_warnings = []
    session.metadata.pop("supplier_parse", None)
    session.metadata.pop("confirmed_supplier_key", None)
    _clear_match_state(session)
    _invalidate_export(session)


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
            _clear_match_state(session)
            _invalidate_export(session)
            return session

    def detect_supplier_pdf(
        self,
        session_id: str,
        *,
        filename: str,
        stream: BinaryIO,
    ) -> tuple[ProcessingSession, dict[str, object]]:
        """Store a PDF and detect the supplier without parsing prices.

        Price extraction must wait for :meth:`confirm_supplier_pdf`.
        A detection failure still keeps a valid upload so the user can
        manually select and confirm a supplier.
        """
        from gheymatyar.suppliers.detection import Confidence, DetectionResult

        with self._store.session_lock(session_id):
            session = self._store.require(session_id)
            assert session.work_dir is not None
            safe_name = _safe_filename(filename, default="supplier.pdf")

            staging = session.work_dir / f"supplier.staging.{uuid4().hex}.pdf"
            staging.write_bytes(stream.read())
            try:
                detection = self._registry.detect(staging)
            except Exception as exc:  # noqa: BLE001 — keep upload for manual recovery
                detection = DetectionResult(
                    detected_supplier_id=None,
                    detected_supplier_name=None,
                    confidence=Confidence.UNKNOWN,
                    evidence=["detection_error", str(exc)[:200]],
                    requires_confirmation=True,
                    text_extracted=False,
                    ocr_used=False,
                )

            final = session.work_dir / "supplier.pdf"
            staging.replace(final)

            detection_payload = detection.to_api_dict()
            session.pdf_filename = safe_name
            session.pdf_path = final
            _revoke_supplier_confirmation(session)
            session.supplier_key = detection.detected_supplier_id
            session.supplier_display_name = detection.detected_supplier_name
            session.metadata["detection"] = detection_payload
            return session, detection_payload

    def confirm_supplier_pdf(
        self,
        session_id: str,
        *,
        supplier_key: str,
    ) -> ProcessingSession:
        """Parse the already-uploaded PDF with the user-confirmed supplier."""
        with self._store.session_lock(session_id):
            session = self._store.require(session_id)
            if session.pdf_path is None or not session.pdf_path.is_file():
                raise ValueError(
                    "Supplier PDF has not been uploaded; detect a PDF first"
                )
            processor = self._registry.get(supplier_key)
            try:
                self._registry.validate_pdf_for_supplier(
                    session.pdf_path, supplier_key
                )
                parse_result = processor.parse_pdf(session.pdf_path)
            except Exception:
                # Keep the uploaded PDF; clear any prior confirmed results.
                _revoke_supplier_confirmation(session)
                # Preserve the user's attempted selection for the confirmation UI.
                session.supplier_key = processor.supplier_key
                session.supplier_display_name = processor.display_name
                raise

            session.supplier_key = processor.supplier_key
            session.supplier_display_name = processor.display_name
            session.supplier_confirmed = True
            session.supplier_items = list(parse_result.items)
            session.parse_warnings = list(parse_result.warnings)
            session.metadata["supplier_parse"] = parse_result.source_metadata
            session.metadata["confirmed_supplier_key"] = processor.supplier_key
            _clear_match_state(session)
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
        """Upload a PDF with an explicit supplier key (treated as confirmation)."""
        with self._store.session_lock(session_id):
            session = self._store.require(session_id)
            assert session.work_dir is not None
            processor = self._registry.get(supplier_key)
            safe_name = _safe_filename(filename, default="supplier.pdf")

            staging = session.work_dir / f"supplier.staging.{uuid4().hex}.pdf"
            staging.write_bytes(stream.read())
            try:
                self._registry.validate_pdf_for_supplier(staging, supplier_key)
                parse_result = processor.parse_pdf(staging)
            except Exception:
                staging.unlink(missing_ok=True)
                raise

            final = session.work_dir / "supplier.pdf"
            staging.replace(final)

            session.supplier_key = processor.supplier_key
            session.supplier_display_name = processor.display_name
            session.supplier_confirmed = True
            session.pdf_filename = safe_name
            session.pdf_path = final
            session.supplier_items = list(parse_result.items)
            session.parse_warnings = list(parse_result.warnings)
            session.metadata["supplier_parse"] = parse_result.source_metadata
            session.metadata["confirmed_supplier_key"] = processor.supplier_key
            session.metadata.pop("detection", None)
            _clear_match_state(session)
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
        if not session.supplier_confirmed:
            raise ValueError(
                "Supplier has not been confirmed; confirm the detected supplier first"
            )
        if not session.supplier_items or not session.supplier_key:
            raise ValueError("Supplier PDF has not been uploaded")

        processor = self._registry.get(session.supplier_key)
        supplier_row = self._ensure_supplier_row(db_session, processor)
        ignored = ProductDecisionRepository(db_session).ignored_identity_keys(
            supplier_row.id
        )
        match_result, candidates, threshold = self._match_candidates(
            session,
            db_session,
            processor,
            supplier_id=supplier_row.id,
            ignored_identities=ignored,
            suspicious_percent_threshold=suspicious_percent_threshold,
        )
        session.candidates = candidates
        session.matched_count = match_result.matched_count
        session.unmatched_count = match_result.unmatched_count
        session.ambiguous_count = match_result.ambiguous_count
        session.ignored_count = match_result.ignored_count
        session.metadata["suspicious_percent_threshold"] = str(threshold)
        session.metadata.pop(_MANUAL_BASIS_KEY, None)
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
            if self._identity_is_ignored(session, db_session, processor, candidate):
                raise ValueError(IGNORED_PRODUCT_MESSAGE)
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
                warnings=list(candidate.pricing_blockers),
                pricing_blockers=list(candidate.pricing_blockers),
                source_currency=candidate.source_currency,
                price_basis=candidate.price_basis,
                tax_state=candidate.tax_state,
                source_page=candidate.source_page,
                source_unit=candidate.source_unit,
                suggestions=[],
            )
            updated = apply_sale_compatibility(
                updated,
                target_unit=product.unit,
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
            if save:
                supplier_row = self._ensure_supplier_row(db_session, processor)
                MappingRepository(db_session).upsert(
                    supplier_id=supplier_row.id,
                    supplier_name_raw=candidate.supplier_name,
                    supplier_name_normalized=processor.normalize_supplier_name(
                        candidate.supplier_name
                    ),
                    supplier_code=candidate.supplier_code,
                    unit=candidate.source_unit,
                    pioneers_name_raw=product.name,
                    pioneers_code=product.code,
                    mapping_type=MappingType.MANUAL,
                )
                commit_or_raise(db_session)
            session.replace_candidate(updated)
            self._recount(session)
            self._remember_manual_basis(session, db_session, processor, updated)
            _invalidate_export(session)
            return updated

    def ignore_candidate(
        self,
        session_id: str,
        db_session: Session,
        *,
        candidate_id: str,
    ) -> UpdateCandidate:
        """Soft-delete a supplier product. Pioneers rows are not modified."""
        with self._store.session_lock(session_id):
            session = self._store.require(session_id)
            candidate = session.get_candidate(candidate_id)
            if candidate is None:
                raise KeyError(candidate_id)
            processor, supplier_row = self._require_supplier(session, db_session)
            identity = _candidate_identity(processor, candidate)
            ProductDecisionRepository(db_session).ignore(
                supplier_id=supplier_row.id,
                supplier_name_raw=candidate.supplier_name,
                supplier_name_normalized=processor.normalize_supplier_name(
                    candidate.supplier_name
                ),
                supplier_code=candidate.supplier_code,
                unit=candidate.source_unit,
            )
            commit_or_raise(db_session)
            updated = candidate
            for current in list(session.candidates):
                if _candidate_identity(processor, current) != identity:
                    continue
                marked = _as_ignored(current)
                session.replace_candidate(marked)
                if current.candidate_id == candidate_id:
                    updated = marked
            self._recount(session)
            _invalidate_export(session)
            return updated

    def restore_candidate(
        self,
        session_id: str,
        db_session: Session,
        *,
        candidate_id: str,
    ) -> UpdateCandidate:
        """Clear a soft-delete and match that product again.

        Other rows keep an explicit exclusion, and an ``APPROVE`` only when
        they still match the same Pioneers row. The restored product itself is
        matched from scratch.
        """
        with self._store.session_lock(session_id):
            session = self._store.require(session_id)
            candidate = session.get_candidate(candidate_id)
            if candidate is None:
                raise KeyError(candidate_id)
            processor, supplier_row = self._require_supplier(session, db_session)
            identity = _candidate_identity(processor, candidate)
            decisions = ProductDecisionRepository(db_session)
            for name in _decision_names(processor, session, candidate):
                decisions.restore(
                    supplier_id=supplier_row.id,
                    supplier_name_raw=candidate.supplier_name,
                    supplier_name_normalized=name,
                    supplier_code=candidate.supplier_code,
                    unit=candidate.source_unit,
                )
            commit_or_raise(db_session)
            ignored = ProductDecisionRepository(db_session).ignored_identity_keys(
                supplier_row.id
            )
            _match_result, candidates, _threshold = self._match_candidates(
                session,
                db_session,
                processor,
                supplier_id=supplier_row.id,
                ignored_identities=ignored,
                suspicious_percent_threshold=session.metadata.get(
                    "suspicious_percent_threshold"
                ),
            )
            self._replace_candidates_preserving_reviews(
                session,
                processor,
                candidates,
                preserve_local_exclude=True,
                release_identity=identity,
                require_review_on_target_change=True,
            )
            restored = session.get_candidate(candidate_id)
            if restored is None or _candidate_identity(processor, restored) != identity:
                # Identity still present, but the previous id was not reused.
                restored = next(
                    (
                        item
                        for item in session.candidates
                        if _candidate_identity(processor, item) == identity
                    ),
                    None,
                )
            if restored is None:
                raise KeyError(candidate_id)
            _invalidate_export(session)
            return restored

    def apply_saved_ignores(
        self, session_id: str, db_session: Session
    ) -> ProcessingSession:
        """Re-apply persistent ignores onto an in-memory session."""
        with self._store.session_lock(session_id):
            session = self._store.require(session_id)
            self._apply_saved_ignores_unlocked(session, db_session)
            return session

    def set_review_decision(
        self,
        session_id: str,
        *,
        candidate_id: str,
        decision: ReviewDecision,
        db_session: Session | None = None,
    ) -> UpdateCandidate:
        with self._store.session_lock(session_id):
            session = self._store.require(session_id)
            if db_session is not None:
                self._apply_saved_ignores_unlocked(session, db_session)
            candidate = session.get_candidate(candidate_id)
            if candidate is None:
                raise KeyError(candidate_id)
            if (
                candidate.status is MatchStatus.IGNORED
                and decision is not ReviewDecision.EXCLUDE
            ):
                raise ValueError(IGNORED_PRODUCT_MESSAGE)
            if (
                candidate.status != MatchStatus.MATCHED
                and decision != ReviewDecision.EXCLUDE
            ):
                raise ValueError("only matched candidates can be included or approved")
            if decision == ReviewDecision.APPROVE and candidate.pricing_blockers:
                raise ValueError(
                    "cannot approve a candidate while a supplier price restriction is unresolved"
                )
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

    def export_excel(
        self, session_id: str, db_session: Session | None = None
    ) -> ExcelUpdateResult:
        with self._store.session_lock(session_id):
            session = self._store.require(session_id)
            for _ in range(4):
                try:
                    return self._export_excel_unlocked(session, db_session)
                except _DecisionsChanged:
                    continue
            raise ValueError("decisions changed during export; retry")

    def export_for_download(
        self,
        session_id: str,
        db_session: Session | None = None,
        *,
        fmt: str = DEFAULT_EXPORT_FORMAT,
    ) -> tuple[ExcelUpdateResult, ExportedFile]:
        """Export, then describe the file a ``fmt`` download will serve."""
        _require_export_format(fmt)
        with self._store.session_lock(session_id):
            result = self.export_excel(session_id, db_session)
            session = self._store.require(session_id)
            sha_key = (
                _EXPORT_LEGACY_SHA_KEY if fmt == EXPORT_FORMAT_XLS else _EXPORT_SHA_KEY
            )
            return result, ExportedFile(
                format=fmt,
                filename=_download_name(session, fmt),
                content_sha256=str(session.metadata[sha_key]),
                exported_row_count=int(session.metadata[_EXPORT_ROW_COUNT_KEY]),
            )

    def read_fresh_workbook(
        self,
        session_id: str,
        db_session: Session,
        *,
        fmt: str = DEFAULT_EXPORT_FORMAT,
    ) -> tuple[bytes, str, int, str]:
        """Return export bytes that match the current SQLite decisions.

        ``fmt`` picks the Pioneers ``.xls`` (default) or the ``.xlsx`` it was
        rendered from. Both are written together and bound to the same
        decisions. A missing workbook stays a not-found result so an
        in-session review change that deleted the file is not silently
        rewritten. A file that is still on disk is served only when its
        decision fingerprint still matches. Otherwise the session is rematched
        from SQLite and the workbook is rewritten before any bytes are
        returned.
        """
        _require_export_format(fmt)
        with self._store.session_lock(session_id):
            session = self._store.require(session_id)
            if not session.supplier_confirmed:
                raise ValueError(
                    "Supplier has not been confirmed; confirm the detected supplier first"
                )
            if not _export_available(session, fmt):
                raise FileNotFoundError("export not available; run export first")
            for _ in range(4):
                self._reconcile_saved_decisions(session, db_session)
                current = self._workbook_stamp(session, db_session)
                recorded = session.metadata.get(_EXPORT_FINGERPRINT_KEY)
                if recorded == current and _export_available(session, fmt):
                    data = _export_path(session, fmt).read_bytes()  # type: ignore[union-attr]
                    served = _bound_export(session, data, fmt)
                    if (
                        served is not None
                        and self._workbook_stamp(session, db_session) == recorded
                    ):
                        return served
                try:
                    self._export_excel_unlocked(session, db_session)
                except _DecisionsChanged:
                    continue
                if _export_available(session, fmt):
                    data = _export_path(session, fmt).read_bytes()  # type: ignore[union-attr]
                    served = _bound_export(session, data, fmt)
                    if served is not None and session.metadata.get(
                        _EXPORT_FINGERPRINT_KEY
                    ) == (self._workbook_stamp(session, db_session)):
                        return served
            raise ValueError(
                "export changed while it was being prepared; retry download"
            )

    def _decision_fingerprint(
        self, session: ProcessingSession, db_session: Session
    ) -> str:
        if not session.supplier_key:
            return "none"
        try:
            processor = self._registry.get(session.supplier_key)
        except UnsupportedSupplierError:
            return "none"
        supplier = self._find_supplier_row(db_session, processor)
        if supplier is None:
            return "none"
        return decision_fingerprint(db_session, supplier.id)

    def _workbook_stamp(
        self, session: ProcessingSession, db_session: Session
    ) -> str:
        return workbook_decision_stamp(
            self._decision_fingerprint(session, db_session),
            session.candidates,
        )

    def _remember_manual_basis(
        self,
        session: ProcessingSession,
        db_session: Session,
        processor,
        candidate: UpdateCandidate,
    ) -> None:
        """Record the saved mapping this override was confirmed against.

        Only this product's row is stored. A later ignore of another product
        does not mark a newer correction of this one as already seen.
        """
        identity = _candidate_identity(processor, candidate)
        supplier = self._find_supplier_row(db_session, processor)
        record = None
        if supplier is not None:
            record = MappingRepository(db_session).get_by_identity(
                supplier.id, identity
            )
        basis = dict(session.metadata.get(_MANUAL_BASIS_KEY) or {})
        basis[identity] = _mapping_basis_token(record)
        session.metadata[_MANUAL_BASIS_KEY] = basis

    def _reconcile_saved_decisions(
        self, session: ProcessingSession, db_session: Session
    ) -> None:
        """Retarget candidates from current SQLite mappings and ignores.

        Explicit exclusions stay put. An approval stays only when the Pioneers
        row is unchanged. A saved correction that moves the target does not
        keep the previous approval. A manual target stays only when the saved
        mapping for that same product is unchanged, and a save=false choice is
        never written to SQLite. An ignore still removes the row from export.
        """
        if not session.supplier_key or not session.supplier_items:
            return
        processor, supplier_row = self._require_supplier(session, db_session)
        ignored = ProductDecisionRepository(db_session).ignored_identity_keys(
            supplier_row.id
        )
        basis = dict(session.metadata.get(_MANUAL_BASIS_KEY) or {})
        repository = MappingRepository(db_session)
        tokens = {
            identity: _mapping_basis_token(
                repository.get_by_identity(supplier_row.id, identity)
            )
            for identity in basis
        }
        _match_result, candidates, _threshold = self._match_candidates(
            session,
            db_session,
            processor,
            supplier_id=supplier_row.id,
            ignored_identities=ignored,
            suspicious_percent_threshold=session.metadata.get(
                "suspicious_percent_threshold"
            ),
        )
        self._replace_candidates_preserving_reviews(
            session,
            processor,
            candidates,
            preserve_local_exclude=True,
            require_review_on_target_change=True,
            manual_basis=basis,
            mapping_tokens=tokens,
        )

    def _export_excel_unlocked(
        self, session: ProcessingSession, db_session: Session | None
    ) -> ExcelUpdateResult:
        if not session.supplier_confirmed:
            raise ValueError(
                "Supplier has not been confirmed; confirm the detected supplier first"
            )
        if session.pioneers_path is None or not session.pioneers_path.is_file():
            raise ValueError("Pioneers Excel has not been uploaded")
        assert session.work_dir is not None

        if db_session is not None:
            self._reconcile_saved_decisions(session, db_session)
            self._apply_saved_ignores_unlocked(session, db_session)
        fingerprint_before = (
            self._decision_fingerprint(session, db_session)
            if db_session is not None
            else None
        )

        # Snapshot decisions under the same lock that review mutations use.
        guarded = apply_price_warnings(
            _refresh_sale_compatibility(session),
            suspicious_percent_threshold=resolve_suspicious_percent_threshold(
                request_value=session.metadata.get("suspicious_percent_threshold"),
                default=DEFAULT_SUSPICIOUS_PERCENT_THRESHOLD,
            ),
            conflicted_row_numbers=session.conflicted_row_numbers,
        )
        session.candidates = guarded

        updates = assemble_export_updates(session.candidates)
        if not updates:
            _invalidate_export(session)
            raise ValueError("no approved updates available for export")

        output = session.work_dir / "pioneers_updated.xlsx"
        if output.exists():
            output.unlink()
        result = update_final_sale_prices(session.pioneers_path, output, updates)
        if db_session is not None:
            fingerprint_after = self._decision_fingerprint(session, db_session)
            if fingerprint_after != fingerprint_before:
                _invalidate_export(session)
                if output.is_file():
                    output.unlink()
                raise _DecisionsChanged()
            session.metadata[_EXPORT_FINGERPRINT_KEY] = workbook_decision_stamp(
                fingerprint_after, session.candidates
            )
        digest = hashlib.sha256(output.read_bytes()).hexdigest()
        if digest != result.content_sha256:
            _invalidate_export(session)
            raise ValueError("exported workbook does not match the recorded content")
        # Pioneers imports an Excel 97–2003 .xls, rendered from the verified
        # workbook so both files carry the same approved rows and prices.
        legacy_output = session.work_dir / "pioneers_updated.xls"
        legacy_output.unlink(missing_ok=True)
        try:
            legacy = write_pioneers_legacy_xls(output, legacy_output, result.changes)
            if legacy.exported_row_count != result.exported_row_count:
                raise ValueError(
                    "Pioneers .xls export row count does not match the approved workbook"
                )
        except Exception:
            _invalidate_export(session)
            output.unlink(missing_ok=True)
            legacy_output.unlink(missing_ok=True)
            raise
        session.metadata[_EXPORT_ROW_COUNT_KEY] = result.exported_row_count
        session.metadata[_EXPORT_SHA_KEY] = digest
        session.metadata[_EXPORT_LEGACY_SHA_KEY] = legacy.content_sha256
        session.output_path = output
        session.legacy_output_path = legacy_output
        return result

    def preview_summary(self, session: ProcessingSession) -> dict[str, object]:
        exportable = sum(1 for c in session.candidates if is_exportable(c))
        warned = sum(1 for c in session.candidates if c.warnings)
        detection = session.metadata.get("detection")
        return {
            "session_id": session.session_id,
            "supplier_key": session.supplier_key,
            "supplier_display_name": session.supplier_display_name,
            "supplier_confirmed": session.supplier_confirmed,
            "detection": detection if isinstance(detection, dict) else None,
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
            "ignored_count": session.ignored_count,
            "warning_count": warned,
            "exportable_count": exportable,
            "parse_warnings": session.parse_warnings,
            "export_available": bool(
                session.output_path and session.output_path.is_file()
            ),
        }

    def _match_candidates(
        self,
        session: ProcessingSession,
        db_session: Session,
        processor,
        *,
        supplier_id: int,
        ignored_identities: set[str],
        suspicious_percent_threshold: str | None,
    ):
        saved = [
            SavedNameMapping(
                supplier_name_normalized=row.supplier_name_normalized,
                pioneers_name_raw=row.pioneers_name_raw,
                pioneers_name_normalized=row.pioneers_name_normalized,
                pioneers_code=row.pioneers_code,
                identity_key=row.identity_key,
                supplier_code=row.supplier_code,
                unit_normalized=row.unit_normalized,
                legacy_unscoped=row.legacy_unscoped,
            )
            for row in MappingRepository(db_session).list_for_supplier(supplier_id)
        ]
        match_result = match_supplier_items(
            session.supplier_items,
            session.products,
            processor=processor,
            saved_mappings=saved,
            ignored_identities=ignored_identities,
        )
        saved_setting = SettingsRepository(db_session).get(SETTING_THRESHOLD_KEY)
        threshold = resolve_suspicious_percent_threshold(
            request_value=suspicious_percent_threshold,
            saved_value=saved_setting.value if saved_setting else None,
            default=DEFAULT_SUSPICIOUS_PERCENT_THRESHOLD,
        )
        candidates = apply_price_warnings(
            match_result.candidates,
            suspicious_percent_threshold=threshold,
            conflicted_row_numbers=session.conflicted_row_numbers,
        )
        return match_result, candidates, threshold

    def _require_supplier(self, session: ProcessingSession, db_session: Session):
        if not session.supplier_key:
            raise ValueError("supplier is not set on this session")
        processor = self._registry.get(session.supplier_key)
        return processor, self._ensure_supplier_row(db_session, processor)

    def _identity_is_ignored(
        self,
        session: ProcessingSession,
        db_session: Session,
        processor,
        candidate: UpdateCandidate,
    ) -> bool:
        supplier = self._find_supplier_row(db_session, processor)
        if supplier is None:
            return False
        ignored = ProductDecisionRepository(db_session).ignored_identity_keys(supplier.id)
        return any(
            ident in ignored
            for ident in _candidate_decision_identities(processor, session, candidate)
        )

    def _apply_saved_ignores_unlocked(
        self, session: ProcessingSession, db_session: Session
    ) -> None:
        if not session.supplier_key or not session.candidates:
            return
        try:
            processor = self._registry.get(session.supplier_key)
        except UnsupportedSupplierError:
            return
        supplier = self._find_supplier_row(db_session, processor)
        if supplier is None:
            return
        ignored = ProductDecisionRepository(db_session).ignored_identity_keys(
            supplier.id
        )
        if not ignored:
            return
        changed = False
        for candidate in list(session.candidates):
            if not any(
                ident in ignored
                for ident in _candidate_decision_identities(
                    processor, session, candidate
                )
            ):
                continue
            marked = _as_ignored(candidate)
            if marked is not candidate:
                session.replace_candidate(marked)
                changed = True
        if changed:
            self._recount(session)
            _invalidate_export(session)

    def _replace_candidates_preserving_reviews(
        self,
        session: ProcessingSession,
        processor,
        new_candidates: list[UpdateCandidate],
        *,
        preserve_local_exclude: bool = False,
        release_identity: str | None = None,
        require_review_on_target_change: bool = False,
        manual_basis: dict[str, str] | None = None,
        mapping_tokens: dict[str, str] | None = None,
    ) -> None:
        """Install a fresh match, keeping reviews that still apply."""
        previous: dict[str, list[UpdateCandidate]] = {}
        for candidate in session.candidates:
            previous.setdefault(_candidate_identity(processor, candidate), []).append(
                candidate
            )
        merged: list[UpdateCandidate] = []
        for new_candidate in new_candidates:
            pool = previous.get(_candidate_identity(processor, new_candidate), [])
            old = pool.pop(0) if pool else None
            if old is None:
                merged.append(new_candidate)
                continue
            decision = new_candidate.review_decision
            new_identity = _candidate_identity(processor, new_candidate)
            recorded = None if manual_basis is None else manual_basis.get(new_identity)
            current_token = (
                None if mapping_tokens is None else mapping_tokens.get(new_identity)
            )
            if (
                old.match_type is MappingType.MANUAL
                and new_candidate.status is not MatchStatus.IGNORED
                and recorded is not None
                and recorded == current_token
            ):
                merged.append(old)
                continue
            target_changed = (
                old.status is MatchStatus.MATCHED
                and new_candidate.status is MatchStatus.MATCHED
                and old.row_number != new_candidate.row_number
            )
            if (
                preserve_local_exclude
                and old.review_decision is ReviewDecision.EXCLUDE
                and new_candidate.status is not MatchStatus.IGNORED
                and new_identity != release_identity
            ):
                decision = ReviewDecision.EXCLUDE
            elif target_changed and require_review_on_target_change:
                # A previous approval does not cover a different Pioneers row.
                # The exception is a saved correction of a product that was
                # already approved: that confirmation names the new row, and
                # the existing approval still covers its price warning.
                # Any other changed target stays out of the workbook.
                if (
                    new_candidate.match_type is MappingType.SAVED_MAPPING
                    and old.review_decision is ReviewDecision.APPROVE
                    and not new_candidate.pricing_blockers
                    and IDENTITY_CONFLICT_WARNING not in new_candidate.warnings
                ):
                    decision = ReviewDecision.APPROVE
                else:
                    decision = ReviewDecision.EXCLUDE
            elif (
                old.review_decision is ReviewDecision.APPROVE
                and old.status is MatchStatus.MATCHED
                and new_candidate.status is MatchStatus.MATCHED
                and new_candidate.row_number == old.row_number
                and not new_candidate.pricing_blockers
                and IDENTITY_CONFLICT_WARNING not in new_candidate.warnings
            ):
                decision = ReviewDecision.APPROVE
            merged.append(
                new_candidate.model_copy(
                    update={
                        "candidate_id": old.candidate_id,
                        "review_decision": decision,
                    }
                )
            )
        session.candidates = merged
        self._recount(session)

    @staticmethod
    def _find_supplier_row(db_session: Session, processor) -> SupplierRecord | None:
        repo = SupplierRepository(db_session)
        existing = repo.get_by_name(processor.display_name)
        if existing is not None:
            return existing
        for row in repo.list_all():
            if row.parser_type == processor.supplier_key:
                return row
        return None

    @staticmethod
    def _ensure_supplier_row(db_session: Session, processor) -> SupplierRecord:
        existing = ProcessingService._find_supplier_row(db_session, processor)
        if existing is not None:
            return existing
        return SupplierRepository(db_session).create(
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
        session.ignored_count = sum(
            1 for c in session.candidates if c.status == MatchStatus.IGNORED
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
        "pricing_blockers": list(candidate.pricing_blockers),
        "source_currency": candidate.source_currency,
        "price_basis": candidate.price_basis,
        "tax_state": candidate.tax_state,
        "source_page": candidate.source_page,
        "source_unit": candidate.source_unit,
        "suggestions": list(candidate.suggestions),
        "exportable": is_exportable(candidate),
        "supplier_name_normalized": normalize_product_name(candidate.supplier_name),
    }
