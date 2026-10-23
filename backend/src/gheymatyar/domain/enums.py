"""Typed enumerations used by domain models."""

from enum import Enum


class MappingType(str, Enum):
    """How a supplier product was linked to a Pioneers product.

    Also reused as ``UpdateCandidate.match_type`` so match provenance
    stays aligned with mapping semantics.
    """

    SAVED_MAPPING = "SAVED_MAPPING"
    EXACT_NAME = "EXACT_NAME"
    MANUAL = "MANUAL"


class MatchStatus(str, Enum):
    """Match quality of an update candidate against the Pioneers catalog."""

    MATCHED = "MATCHED"
    UNMATCHED = "UNMATCHED"
    AMBIGUOUS = "AMBIGUOUS"
    # Soft-deleted supplier product. Excluded from review, preview, and export.
    IGNORED = "IGNORED"


class ReviewDecision(str, Enum):
    """Per-candidate export inclusion decision."""

    INCLUDE = "INCLUDE"
    EXCLUDE = "EXCLUDE"
    APPROVE = "APPROVE"  # include despite validation warnings
