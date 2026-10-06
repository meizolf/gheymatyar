"""Typed enumerations used by domain models."""

from enum import Enum


class MappingType(str, Enum):
    """How a supplier SKU was linked to a Pioneers product.

    Also reused as ``UpdateCandidate.match_type`` so match provenance
    stays aligned with mapping semantics (AUTO_CODE / AUTO_BARCODE / MANUAL).
    """

    AUTO_CODE = "AUTO_CODE"
    AUTO_BARCODE = "AUTO_BARCODE"
    MANUAL = "MANUAL"


class MatchStatus(str, Enum):
    """Match quality of an update candidate against the Pioneers catalog.

    This is intentionally *not* a review/workflow lifecycle (approve/apply).
    A separate workflow enum can be introduced later when persistence and
    review flows land; Step 2 only needs match outcome.
    """

    MATCHED = "MATCHED"
    UNMATCHED = "UNMATCHED"
    AMBIGUOUS = "AMBIGUOUS"
