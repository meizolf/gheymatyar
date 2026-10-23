"""Offline supplier detection from PDF content (text layer, optional OCR).

Detection is a suggestion only. Callers must require explicit user confirmation
before running a supplier processor or exporting prices.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Sequence

import pymupdf

if TYPE_CHECKING:
    from gheymatyar.suppliers.registry import SupplierProcessorRegistry

logger = logging.getLogger(__name__)

__all__ = [
    "Confidence",
    "DetectionResult",
    "DetectionRules",
    "SupplierDetector",
    "extract_pdf_text_for_detection",
    "matching_strong_markers",
    "try_offline_ocr",
]


class Confidence(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class DetectionRules:
    """Extensible per-supplier markers registered alongside the processor.

    Strong markers identify the company/brand. Supporting markers (currency
    labels, generic layout phrases) only reinforce a strong hit — they never
    assign a supplier on their own. Weak markers are product-specific hints.
    """

    strong_markers: Sequence[str] = ()
    weak_markers: Sequence[str] = ()
    #: Counted only when at least one strong marker also matches.
    supporting_markers: Sequence[str] = ()
    websites: Sequence[str] = ()


@dataclass(frozen=True)
class DetectionResult:
    detected_supplier_id: str | None
    detected_supplier_name: str | None
    confidence: Confidence
    evidence: list[str] = field(default_factory=list)
    requires_confirmation: bool = True
    text_extracted: bool = False
    ocr_used: bool = False
    scores: dict[str, int] = field(default_factory=dict)

    def to_api_dict(self) -> dict[str, object]:
        return {
            "detected_supplier_id": self.detected_supplier_id,
            "detected_supplier_name": self.detected_supplier_name,
            "confidence": self.confidence.value,
            "evidence": list(self.evidence),
            "requires_confirmation": True,
            "text_extracted": self.text_extracted,
            "ocr_used": self.ocr_used,
        }


def extract_pdf_text_for_detection(
    path: str | Path, *, max_pages: int | None = 3
) -> tuple[str, bool]:
    """Return (text, has_text_layer) using PyMuPDF.

    ``max_pages=None`` reads every page (used for confirmation identity checks).
    """
    source = Path(path)
    chunks: list[str] = []
    with pymupdf.open(source) as doc:
        if max_pages is None:
            limit = len(doc)
        else:
            limit = min(len(doc), max(1, max_pages))
        for index in range(limit):
            page_text = doc[index].get_text("text") or ""
            if page_text.strip():
                chunks.append(page_text)
    text = "\n".join(chunks)
    return text, bool(text.strip())


def try_offline_ocr(path: str | Path, *, max_pages: int = 2) -> str:
    """Best-effort offline OCR when the PDF has no usable text layer.

    Uses PyMuPDF page rasters plus optional ``pytesseract`` + Pillow when they
    are installed. Never contacts the network. Returns empty string when OCR
    tooling is unavailable (the Windows package does not bundle Tesseract).
    """
    try:
        import pytesseract  # type: ignore[import-not-found]
        from PIL import Image
    except ImportError:
        logger.debug("offline OCR skipped: pytesseract/Pillow not available")
        return ""

    source = Path(path)
    parts: list[str] = []
    try:
        with pymupdf.open(source) as doc:
            limit = min(len(doc), max(1, max_pages))
            for index in range(limit):
                page = doc[index]
                # ~150 DPI keeps detection responsive on older Windows PCs.
                pix = page.get_pixmap(matrix=pymupdf.Matrix(1.5, 1.5), alpha=False)
                image = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
                try:
                    text = pytesseract.image_to_string(image, lang="fas+eng")
                except Exception:  # noqa: BLE001 — OCR is best-effort
                    try:
                        text = pytesseract.image_to_string(image, lang="eng")
                    except Exception:  # noqa: BLE001
                        continue
                if text and text.strip():
                    parts.append(text)
    except Exception as exc:  # noqa: BLE001
        logger.debug("offline OCR failed for %s: %s", source, exc)
        return ""
    return "\n".join(parts)


def _normalize_haystack(text: str) -> str:
    return text.casefold()


def _marker_in_text(marker: str, haystack: str, haystack_folded: str) -> bool:
    if not marker:
        return False
    if marker.isascii():
        return marker.casefold() in haystack_folded
    return marker in haystack


def _dedupe_overlapping_markers(markers: Sequence[str]) -> list[str]:
    """Keep longest hits; drop aliases that are substrings of a longer hit.

    Example: matching both ``آذین لوله`` and ``آذین`` counts once.
    """
    ordered = sorted({m for m in markers if m}, key=lambda m: (-len(m), m))
    kept: list[str] = []
    for marker in ordered:
        folded = marker.casefold() if marker.isascii() else marker
        covered = False
        for existing in kept:
            existing_folded = existing.casefold() if existing.isascii() else existing
            if marker.isascii() and existing.isascii():
                if folded in existing_folded:
                    covered = True
                    break
            elif not marker.isascii() and not existing.isascii():
                if marker in existing:
                    covered = True
                    break
        if not covered:
            kept.append(marker)
    return kept


def matching_strong_markers(text: str, rules: DetectionRules) -> list[str]:
    """Return de-duplicated strong markers found in ``text``."""
    if not text.strip():
        return []
    folded = _normalize_haystack(text)
    hits = [
        marker
        for marker in rules.strong_markers
        if _marker_in_text(marker, text, folded)
    ]
    return _dedupe_overlapping_markers(hits)


def _score_rules(text: str, rules: DetectionRules) -> tuple[int, list[str], bool]:
    """Return (score, evidence, has_strong_identity)."""
    if not text.strip():
        return 0, [], False
    folded = _normalize_haystack(text)
    evidence: list[str] = []

    strong_hits = matching_strong_markers(text, rules)
    has_strong = bool(strong_hits)
    score = 0
    if has_strong:
        # One identity credit regardless of how many aliases overlapped.
        score += 10
        evidence.extend(strong_hits)

    for marker in rules.websites:
        if _marker_in_text(marker, text, folded):
            score += 8
            if marker not in evidence:
                evidence.append(marker)

    if has_strong:
        for marker in rules.supporting_markers:
            if _marker_in_text(marker, text, folded):
                score += 2
                if marker not in evidence:
                    evidence.append(marker)

        for marker in rules.weak_markers:
            if _marker_in_text(marker, text, folded):
                score += 3
                if marker not in evidence:
                    evidence.append(marker)
    else:
        # Weak/supporting hits without a brand identity never assign a supplier.
        # Still record generic evidence for debugging when nothing else matches.
        for marker in (*rules.supporting_markers, *rules.weak_markers):
            if _marker_in_text(marker, text, folded) and marker not in evidence:
                evidence.append(marker)

    return score, evidence, has_strong


def _confidence_from_scores(
    ranked: list[tuple[str, int]],
    *,
    strong_keys: set[str],
) -> Confidence:
    if not ranked or ranked[0][1] <= 0:
        return Confidence.UNKNOWN

    top_key, top_score = ranked[0]
    if top_key not in strong_keys:
        # Generics / weak-only matches must not assign a supplier.
        return Confidence.UNKNOWN

    second_score = ranked[1][1] if len(ranked) > 1 else 0
    margin = top_score - second_score
    competing_strong = [key for key in strong_keys if key != top_key]

    # Two different brands present → never claim HIGH.
    if competing_strong:
        if second_score > 0 and margin < 5:
            return Confidence.UNKNOWN
        return Confidence.LOW

    if top_score >= 10 and margin >= 5:
        return Confidence.HIGH
    if top_score >= 8 and margin >= 3:
        return Confidence.MEDIUM
    if top_score > 0:
        return Confidence.LOW
    return Confidence.UNKNOWN


class SupplierDetector:
    """Score registered suppliers against PDF text (and optional OCR)."""

    def __init__(self, registry: SupplierProcessorRegistry) -> None:
        self._registry = registry

    def detect(self, path: str | Path) -> DetectionResult:
        source = Path(path)
        if not source.is_file():
            return DetectionResult(
                detected_supplier_id=None,
                detected_supplier_name=None,
                confidence=Confidence.UNKNOWN,
                evidence=["pdf_not_found"],
                requires_confirmation=True,
            )

        text, has_text = extract_pdf_text_for_detection(source)
        ocr_used = False
        if not has_text:
            ocr_text = try_offline_ocr(source)
            if ocr_text.strip():
                text = ocr_text
                ocr_used = True
            else:
                evidence = ["no_text_layer"]
                if ocr_text == "":
                    evidence.append("ocr_unavailable_or_empty")
                return DetectionResult(
                    detected_supplier_id=None,
                    detected_supplier_name=None,
                    confidence=Confidence.UNKNOWN,
                    evidence=evidence,
                    requires_confirmation=True,
                    text_extracted=False,
                    ocr_used=False,
                )

        scores: dict[str, int] = {}
        evidence_by_key: dict[str, list[str]] = {}
        strong_keys: set[str] = set()
        display_names: dict[str, str] = {}

        for info in self._registry.list_suppliers():
            processor = self._registry.get(info.key)
            rules = processor.detection_rules()
            score, hits, has_strong = _score_rules(text, rules)
            scores[info.key] = score
            evidence_by_key[info.key] = hits
            if has_strong:
                strong_keys.add(info.key)
            display_names[info.key] = processor.display_name

        ranked = sorted(scores.items(), key=lambda item: (-item[1], item[0]))
        top_key, top_score = ranked[0] if ranked else (None, 0)

        if top_key is None or top_score <= 0 or top_key not in strong_keys:
            generic_evidence: list[str] = []
            for key, _score in ranked:
                for marker in evidence_by_key.get(key, []):
                    if marker not in generic_evidence:
                        generic_evidence.append(marker)
            return DetectionResult(
                detected_supplier_id=None,
                detected_supplier_name=None,
                confidence=Confidence.UNKNOWN,
                evidence=generic_evidence or ["no_matching_supplier_markers"],
                requires_confirmation=True,
                text_extracted=True,
                ocr_used=ocr_used,
                scores=scores,
            )

        confidence = _confidence_from_scores(ranked, strong_keys=strong_keys)
        if confidence is Confidence.UNKNOWN:
            return DetectionResult(
                detected_supplier_id=None,
                detected_supplier_name=None,
                confidence=Confidence.UNKNOWN,
                evidence=evidence_by_key.get(top_key, [])
                + [
                    f"conflict:{key}"
                    for key in sorted(strong_keys)
                    if key != top_key
                ],
                requires_confirmation=True,
                text_extracted=True,
                ocr_used=ocr_used,
                scores=scores,
            )

        return DetectionResult(
            detected_supplier_id=top_key,
            detected_supplier_name=display_names[top_key],
            confidence=confidence,
            evidence=evidence_by_key.get(top_key, []),
            requires_confirmation=True,
            text_extracted=True,
            ocr_used=ocr_used,
            scores=scores,
        )
