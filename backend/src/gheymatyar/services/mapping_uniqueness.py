"""One active supplier product per Pioneers product, per supplier.

Two targets are the same Pioneers product when both have a product code and
the codes match, or, when either has no code, when their normalized names
match. A name typed without its code therefore still collides, while two
products that share a name but have different codes do not. Within one
supplier, at most one *active* supplier product may point at a product:

* a saved, variant-scoped mapping whose supplier product is not ignored
* a matched candidate in the current session (saved, exact-name, or manual)

Legacy name-only mappings are never applied automatically, so they do not
hold a product. Ignored supplier products release theirs.

New and edited mappings are checked here before they are written, under
``MAPPING_WRITE_LOCK`` so two requests cannot both claim the same product.
Duplicates already stored in SQLite are reported, never deleted.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Iterable, Sequence

from gheymatyar.domain.enums import MappingType, MatchStatus, ReviewDecision
from gheymatyar.domain.update_candidate import UpdateCandidate
from gheymatyar.repositories.records import ProductMappingRecord
from gheymatyar.services.name_normalization import normalize_product_name

#: Serializes check-then-write of mappings. GheymatYar runs one process.
MAPPING_WRITE_LOCK = threading.RLock()

DUPLICATE_TARGET_WARNING = (
    "Pioneers product is already matched to another supplier product; "
    "change or remove one of the two mappings"
)

# Which match keeps a contested Pioneers product: an explicit choice in this
# session, then a saved mapping, then an exact name.
_MATCH_PRIORITY = {
    MappingType.MANUAL: 3,
    MappingType.SAVED_MAPPING: 2,
    MappingType.EXACT_NAME: 1,
}


@dataclass(frozen=True)
class PioneersTarget:
    """A Pioneers product as a mapping names it: optional code and a name."""

    code: str | None
    name: str

    def same_as(self, other: PioneersTarget) -> bool:
        if self.code and other.code:
            return self.code == other.code
        return self.name == other.name


def pioneers_target(code: str | None, name: str | None) -> PioneersTarget:
    cleaned = (code or "").strip() or None
    return PioneersTarget(code=cleaned, name=normalize_product_name(name or ""))


def mapping_target(mapping: ProductMappingRecord) -> PioneersTarget:
    return pioneers_target(mapping.pioneers_code, mapping.pioneers_name_normalized)


def candidate_target(candidate: UpdateCandidate) -> PioneersTarget | None:
    if candidate.status is not MatchStatus.MATCHED or candidate.row_number is None:
        return None
    return pioneers_target(candidate.pioneers_code, candidate.pioneers_name)


@dataclass(frozen=True)
class TargetHolder:
    """A supplier product that already holds a Pioneers product."""

    supplier_name: str
    supplier_code: str | None
    unit: str | None
    source: str  # "saved_mapping" or "session_match"
    mapping_id: int | None = None
    candidate_id: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "supplier_name": self.supplier_name,
            "supplier_code": self.supplier_code,
            "unit": self.unit,
            "source": self.source,
            "mapping_id": self.mapping_id,
            "candidate_id": self.candidate_id,
        }


class DuplicateMappingTargetError(ValueError):
    """The selected Pioneers product is already held by another supplier product."""

    def __init__(
        self,
        *,
        pioneers_code: str | None,
        pioneers_name: str,
        holders: Sequence[TargetHolder],
    ) -> None:
        self.pioneers_code = pioneers_code
        self.pioneers_name = pioneers_name
        self.holders = list(holders)
        names = ", ".join(f"«{holder.supplier_name}»" for holder in self.holders)
        label = pioneers_code or pioneers_name
        super().__init__(
            f"Pioneers product {label} is already mapped to supplier product "
            f"{names}; change or delete that mapping first"
        )

    def to_detail(self) -> dict[str, object]:
        return {
            "code": "duplicate_mapping_target",
            "message": str(self),
            "pioneers_code": self.pioneers_code,
            "pioneers_name": self.pioneers_name,
            "conflicts": [holder.to_dict() for holder in self.holders],
        }


def active_mappings(
    mappings: Iterable[ProductMappingRecord], ignored_identities: set[str]
) -> list[ProductMappingRecord]:
    return [
        mapping
        for mapping in mappings
        if not mapping.legacy_unscoped and mapping.identity_key not in ignored_identities
    ]


def saved_holders(
    mappings: Iterable[ProductMappingRecord],
    *,
    target: PioneersTarget,
    ignored_identities: set[str],
    exclude_identities: Iterable[str] = (),
    exclude_mapping_id: int | None = None,
) -> list[TargetHolder]:
    """Active saved mappings that already point at ``target``."""
    excluded = set(exclude_identities)
    return [
        TargetHolder(
            supplier_name=mapping.supplier_name_raw,
            supplier_code=mapping.supplier_code,
            unit=mapping.unit_normalized,
            source="saved_mapping",
            mapping_id=mapping.id,
        )
        for mapping in active_mappings(mappings, ignored_identities)
        if mapping_target(mapping).same_as(target)
        and mapping.identity_key not in excluded
        and mapping.id != exclude_mapping_id
    ]


def session_holders(
    candidates: Iterable[UpdateCandidate],
    *,
    target: PioneersTarget,
    exclude_candidate_id: str | None,
) -> list[TargetHolder]:
    """Matched candidates in this session that already point at ``target``."""
    return [
        TargetHolder(
            supplier_name=candidate.supplier_name,
            supplier_code=candidate.supplier_code,
            unit=candidate.source_unit,
            source="session_match",
            candidate_id=candidate.candidate_id,
        )
        for candidate in candidates
        if candidate.candidate_id != exclude_candidate_id
        and (held := candidate_target(candidate)) is not None
        and held.same_as(target)
    ]


def merge_holders(*groups: Sequence[TargetHolder]) -> list[TargetHolder]:
    """One entry per supplier product, saved mappings first."""
    merged: list[TargetHolder] = []
    seen: set[tuple[str, str | None, str | None]] = set()
    for group in groups:
        for holder in group:
            key = (
                normalize_product_name(holder.supplier_name),
                holder.supplier_code or None,
                normalize_product_name(holder.unit) if holder.unit else None,
            )
            if key in seen:
                continue
            seen.add(key)
            merged.append(holder)
    return merged


def duplicate_saved_targets(
    mappings: Iterable[ProductMappingRecord], ignored_identities: set[str]
) -> dict[int, list[ProductMappingRecord]]:
    """For each active mapping that shares its target, the other holders."""
    active = [(m, mapping_target(m)) for m in active_mappings(mappings, ignored_identities)]
    by_code: dict[str, list[int]] = {}
    by_name: dict[str, list[int]] = {}
    for index, (_mapping, target) in enumerate(active):
        if target.code:
            by_code.setdefault(target.code, []).append(index)
        by_name.setdefault(target.name, []).append(index)
    duplicates: dict[int, list[ProductMappingRecord]] = {}
    for index, (mapping, target) in enumerate(active):
        nearby = set(by_code.get(target.code, [])) if target.code else set()
        nearby.update(by_name.get(target.name, []))
        others = [
            active[other][0]
            for other in sorted(nearby)
            if other != index and active[other][1].same_as(target)
        ]
        if others:
            duplicates[mapping.id] = others
    return duplicates


def resolve_duplicate_targets(
    candidates: Sequence[UpdateCandidate],
) -> list[UpdateCandidate]:
    """Keep at most one matched candidate per Pioneers row.

    The highest-priority match keeps the row. When the top priority is shared,
    for example two saved mappings already duplicated in SQLite, none keeps
    it. Every other candidate becomes ``AMBIGUOUS`` with the contested product
    as its only suggestion and ``DUPLICATE_TARGET_WARNING``, excluded from
    export. Nothing is deleted.
    """
    groups: dict[int, list[int]] = {}
    for index, candidate in enumerate(candidates):
        if candidate.status is MatchStatus.MATCHED and candidate.row_number is not None:
            groups.setdefault(candidate.row_number, []).append(index)
    demote: set[int] = set()
    for indexes in groups.values():
        if len(indexes) < 2:
            continue
        ranks = {
            index: _MATCH_PRIORITY.get(candidates[index].match_type, 0)
            for index in indexes
        }
        best = max(ranks.values())
        winners = [index for index in indexes if ranks[index] == best]
        keep = winners[0] if len(winners) == 1 else None
        demote.update(index for index in indexes if index != keep)
    if not demote:
        return list(candidates)
    resolved = list(candidates)
    for index in demote:
        resolved[index] = _demoted(candidates[index], candidates, groups)
    return resolved


def _demoted(
    candidate: UpdateCandidate,
    candidates: Sequence[UpdateCandidate],
    groups: dict[int, list[int]],
) -> UpdateCandidate:
    row = candidate.row_number
    assert row is not None
    others = [
        candidates[index].supplier_name
        for index in groups[row]
        if candidates[index].candidate_id != candidate.candidate_id
    ]
    suggestion = {
        "row_number": row,
        "pioneers_code": candidate.pioneers_code,
        "pioneers_name": candidate.pioneers_name,
        "sale_price": str(candidate.old_price) if candidate.old_price is not None else None,
        "score": 1.0,
        "held_by": others,
    }
    warnings = [DUPLICATE_TARGET_WARNING]
    warnings.extend(w for w in candidate.warnings if w not in warnings)
    return candidate.model_copy(
        update={
            "status": MatchStatus.AMBIGUOUS,
            "review_decision": ReviewDecision.EXCLUDE,
            "row_number": None,
            "pioneers_code": None,
            "pioneers_name": None,
            "old_price": None,
            "absolute_change": None,
            "percentage_change": None,
            "warnings": warnings,
            "suggestions": [suggestion],
        }
    )
