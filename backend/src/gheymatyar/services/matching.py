"""Name-based product matching between supplier items and Pioneers products."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Iterable, Sequence
from uuid import uuid4

from gheymatyar.domain.enums import MappingType, MatchStatus, ReviewDecision
from gheymatyar.domain.product import PioneersProduct
from gheymatyar.domain.supplier_item import SupplierPriceItem
from gheymatyar.domain.update_candidate import UpdateCandidate
from gheymatyar.services.name_normalization import name_similarity, normalize_product_name
from gheymatyar.services.price_validation import apply_sale_compatibility
from gheymatyar.services.product_identity import supplier_product_identity
from gheymatyar.suppliers.base import BaseSupplierProcessor


@dataclass(frozen=True)
class SavedNameMapping:
    """A previously confirmed supplier→Pioneers name mapping."""

    supplier_name_normalized: str
    pioneers_name_raw: str
    pioneers_name_normalized: str
    pioneers_code: str | None = None
    identity_key: str | None = None
    supplier_code: str | None = None
    unit_normalized: str | None = None
    legacy_unscoped: bool = False


@dataclass
class MatchResult:
    candidates: list[UpdateCandidate] = field(default_factory=list)
    matched_count: int = 0
    unmatched_count: int = 0
    ambiguous_count: int = 0
    ignored_count: int = 0


# A saved mapping whose Pioneers target is gone or no longer unique must not
# fall through to a different automatic match.
SAVED_TARGET_UNRESOLVED_WARNING = (
    "saved Pioneers mapping no longer identifies a single product in the "
    "current workbook; remap before this product can be included"
)

# A name-only mapping saved before variants were stored does not record which
# code or unit it belonged to. One later upload cannot prove it is that variant.
LEGACY_VARIANT_AMBIGUOUS_WARNING = (
    "saved mapping has no supplier code or unit, so it cannot be applied "
    "to a specific variant; confirm this code and unit before it can be included"
)


def _index_by_normalized_name(
    products: Sequence[PioneersProduct],
) -> dict[str, list[PioneersProduct]]:
    index: dict[str, list[PioneersProduct]] = {}
    for product in products:
        key = normalize_product_name(product.name)
        index.setdefault(key, []).append(product)
    return index


def _suggestion_payloads(
    supplier_name: str,
    products: Sequence[PioneersProduct],
    *,
    limit: int = 5,
    min_score: float = 0.35,
) -> list[dict[str, object]]:
    scored: list[tuple[float, PioneersProduct]] = []
    for product in products:
        score = name_similarity(supplier_name, product.name)
        if score >= min_score:
            scored.append((score, product))
    scored.sort(key=lambda pair: (-pair[0], pair[1].name))
    out: list[dict[str, object]] = []
    for score, product in scored[:limit]:
        out.append(
            {
                "row_number": product.row_number,
                "pioneers_code": product.code,
                "pioneers_name": product.name,
                "sale_price": str(product.sale_price)
                if product.sale_price is not None
                else None,
                "score": round(score, 4),
            }
        )
    return out


NAME_COLLISION_BLOCKER = (
    "supplier name is shared by products with different prices or codes; "
    "automatic export is blocked until the names are distinct"
)


def _string_list(raw: object) -> list[str]:
    if not raw:
        return []
    values = [raw] if isinstance(raw, str) else list(raw)  # type: ignore[arg-type]
    cleaned: list[str] = []
    for value in values:
        text = str(value).strip()
        if text and text not in cleaned:
            cleaned.append(text)
    return cleaned


def _item_review_warnings(item: SupplierPriceItem) -> list[str]:
    """Warnings stored by a supplier processor that must block automatic export."""
    raw = item.raw_values.get("review_warnings") if item.raw_values else None
    return _string_list(raw)


def _hard_blockers(item: SupplierPriceItem, extras: Sequence[str]) -> list[str]:
    """Non-overridable price restrictions from the supplier row."""
    raw = item.raw_values or {}
    blockers = _string_list(raw.get("pricing_blockers"))
    for text in _item_review_warnings(item):
        if text not in blockers:
            blockers.append(text)
    for text in extras:
        if text and text not in blockers:
            blockers.append(text)
    return blockers


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _source_page(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _provenance(item: SupplierPriceItem, blockers: list[str]) -> dict[str, object]:
    raw = item.raw_values or {}
    return {
        "pricing_blockers": blockers,
        "source_currency": _optional_text(raw.get("currency")),
        "price_basis": _optional_text(raw.get("price_basis")),
        "tax_state": _optional_text(raw.get("tax")),
        "source_page": _source_page(raw.get("page")),
        "source_unit": _optional_text(item.unit),
    }


def _colliding_names(
    items: Sequence[SupplierPriceItem],
    processor: BaseSupplierProcessor,
) -> set[str]:
    """Normalized names that belong to more than one distinct supplier row."""
    grouped: dict[str, list[SupplierPriceItem]] = {}
    for item in items:
        key = processor.normalize_supplier_name(item.supplier_name)
        grouped.setdefault(key, []).append(item)
    collisions: set[str] = set()
    for key, group in grouped.items():
        if len(group) < 2:
            continue
        prices = {item.price for item in group}
        codes = {item.supplier_code or "" for item in group}
        if len(prices) > 1 or len(codes) > 1:
            collisions.add(key)
    return collisions


def _price_fields(
    old_price: Decimal | None, new_price: Decimal | None
) -> tuple[Decimal | None, Decimal | None, Decimal | None]:
    if old_price is None or new_price is None:
        return old_price, new_price, None
    absolute = new_price - old_price
    if old_price == 0:
        percentage = None
    else:
        percentage = (absolute / old_price) * Decimal("100")
    return absolute, new_price, percentage


def _saved_identity(mapping: SavedNameMapping) -> str | None:
    """Return the variant key for a scoped mapping.

    ``legacy_unscoped`` rows have no known code or unit. They are not given a
    variant key, even when this upload contains only one item with the name.
    """
    if mapping.legacy_unscoped:
        return None
    if mapping.identity_key:
        return mapping.identity_key
    return None


def item_decision_identities(
    processor: BaseSupplierProcessor, item: SupplierPriceItem
) -> list[str]:
    """Current identity, then prior name identities for the same code and unit.

    A prior name is never matched by supplier code alone.
    """
    current = supplier_product_identity(
        normalized_name=processor.normalize_supplier_name(item.supplier_name),
        supplier_code=item.supplier_code,
        unit=item.unit,
    )
    identities = [current]
    for name in processor.prior_normalized_names(item):
        if not name or not str(name).strip():
            continue
        ident = supplier_product_identity(
            normalized_name=str(name).strip(),
            supplier_code=item.supplier_code,
            unit=item.unit,
        )
        if ident not in identities:
            identities.append(ident)
    return identities


def match_supplier_items(
    items: Sequence[SupplierPriceItem],
    products: Sequence[PioneersProduct],
    *,
    processor: BaseSupplierProcessor,
    saved_mappings: Iterable[SavedNameMapping] = (),
    ignored_identities: Iterable[str] = (),
    suggestion_pool_limit: int = 8,
) -> MatchResult:
    """Match supplier items to Pioneers products by name.

    Priority:
    1. Persistent ignore (soft-delete) — never auto-matched or exported
    2. Saved mapping for this variant (name, supplier code, and unit)
    3. Unique exact normalized-name match
    4. Similar-name suggestions → AMBIGUOUS / UNMATCHED (never auto-confirmed)

    A saved mapping that no longer identifies one current Pioneers product is
    left unmatched for remapping. It does not fall through to another product.
    A legacy name-only mapping does not know the original code or unit, so it
    is never applied automatically and does not fall through to an automatic
    match. Each variant has to be confirmed on its own.
    """
    by_name = _index_by_normalized_name(products)
    by_code: dict[str, list[PioneersProduct]] = {}
    for product in products:
        if product.code:
            by_code.setdefault(product.code, []).append(product)

    scoped: dict[str, SavedNameMapping] = {}
    legacy_by_name: dict[str, list[SavedNameMapping]] = {}
    name_only: dict[str, list[SavedNameMapping]] = {}
    for mapping in saved_mappings:
        if mapping.legacy_unscoped:
            legacy_by_name.setdefault(mapping.supplier_name_normalized, []).append(
                mapping
            )
            continue
        identity_key = _saved_identity(mapping)
        if identity_key:
            scoped[identity_key] = mapping
        else:
            # In-memory name mappings that predate the variant key. A persisted
            # legacy row is legacy_unscoped and is not handled here.
            name_only.setdefault(mapping.supplier_name_normalized, []).append(mapping)
    name_counts: dict[str, int] = {}
    for item in items:
        normalized = processor.normalize_supplier_name(item.supplier_name)
        name_counts[normalized] = name_counts.get(normalized, 0) + 1
    ignored = {key for key in ignored_identities if key}
    collisions = _colliding_names(items, processor)

    result = MatchResult()

    for item in items:
        supplier_name = processor.normalize_supplier_name(item.supplier_name)
        raw_supplier_name = item.supplier_name
        new_price = processor.calculate_final_sale_price(item)
        candidate_id = str(uuid4())
        extras = [NAME_COLLISION_BLOCKER] if supplier_name in collisions else []
        blockers = _hard_blockers(item, extras)
        provenance = _provenance(item, blockers)
        identities = item_decision_identities(processor, item)
        if any(key in ignored for key in identities):
            result.candidates.append(
                UpdateCandidate(
                    candidate_id=candidate_id,
                    row_number=None,
                    pioneers_code=None,
                    pioneers_name=None,
                    supplier_code=item.supplier_code,
                    supplier_name=raw_supplier_name,
                    old_price=None,
                    new_price=new_price,
                    absolute_change=None,
                    percentage_change=None,
                    match_type=None,
                    status=MatchStatus.IGNORED,
                    review_decision=ReviewDecision.EXCLUDE,
                    warnings=list(blockers),
                    **provenance,
                )
            )
            result.ignored_count += 1
            continue

        # 1) Saved mapping — ahead of exact and fuzzy matches.
        saved = next((scoped[key] for key in identities if key in scoped), None)
        legacy_hits = legacy_by_name.get(supplier_name, [])
        if saved is None and legacy_hits:
            suggestions: list[dict[str, object]] = []
            seen_rows: set[int] = set()
            for legacy in legacy_hits:
                _legacy_status, extra = _remap_suggestions(
                    legacy,
                    by_name,
                    by_code,
                    raw_supplier_name,
                    products,
                    suggestion_pool_limit,
                )
                for suggestion in extra:
                    row_number = suggestion.get("row_number")
                    if isinstance(row_number, int) and row_number not in seen_rows:
                        seen_rows.add(row_number)
                        suggestions.append(suggestion)
            result.candidates.append(
                UpdateCandidate(
                    candidate_id=candidate_id,
                    row_number=None,
                    pioneers_code=None,
                    pioneers_name=None,
                    supplier_code=item.supplier_code,
                    supplier_name=raw_supplier_name,
                    old_price=None,
                    new_price=new_price,
                    absolute_change=None,
                    percentage_change=None,
                    match_type=None,
                    status=MatchStatus.AMBIGUOUS,
                    review_decision=ReviewDecision.EXCLUDE,
                    warnings=[LEGACY_VARIANT_AMBIGUOUS_WARNING, *blockers],
                    suggestions=suggestions[:suggestion_pool_limit],
                    **provenance,
                )
            )
            result.ambiguous_count += 1
            continue
        if saved is None:
            name_hits = name_only.get(supplier_name, [])
            if len(name_hits) == 1 and name_counts.get(supplier_name, 0) == 1:
                saved = name_hits[0]
            elif name_hits:
                saved = name_hits[0]
                resolved_name = _resolve_saved_mapping(saved, by_name, by_code)
                status = (
                    MatchStatus.AMBIGUOUS
                    if resolved_name is not None
                    else MatchStatus.UNMATCHED
                )
                _status, suggestions = _remap_suggestions(
                    saved,
                    by_name,
                    by_code,
                    raw_supplier_name,
                    products,
                    suggestion_pool_limit,
                )
                result.candidates.append(
                    UpdateCandidate(
                        candidate_id=candidate_id,
                        row_number=None,
                        pioneers_code=None,
                        pioneers_name=None,
                        supplier_code=item.supplier_code,
                        supplier_name=raw_supplier_name,
                        old_price=None,
                        new_price=new_price,
                        absolute_change=None,
                        percentage_change=None,
                        match_type=None,
                        status=status,
                        review_decision=ReviewDecision.EXCLUDE,
                        warnings=[LEGACY_VARIANT_AMBIGUOUS_WARNING, *blockers],
                        suggestions=suggestions,
                        **provenance,
                    )
                )
                if status is MatchStatus.AMBIGUOUS:
                    result.ambiguous_count += 1
                else:
                    result.unmatched_count += 1
                continue
        if saved is not None:
            resolved = _resolve_saved_mapping(saved, by_name, by_code)
            if resolved is not None:
                absolute, _, percentage = _price_fields(
                    resolved.sale_price, new_price
                )
                result.candidates.append(
                    apply_sale_compatibility(
                        UpdateCandidate(
                            candidate_id=candidate_id,
                            row_number=resolved.row_number,
                            pioneers_code=resolved.code,
                            pioneers_name=resolved.name,
                            supplier_code=item.supplier_code,
                            supplier_name=raw_supplier_name,
                            old_price=resolved.sale_price,
                            new_price=new_price,
                            absolute_change=absolute,
                            percentage_change=percentage,
                            match_type=MappingType.SAVED_MAPPING,
                            status=MatchStatus.MATCHED,
                            review_decision=ReviewDecision.INCLUDE,
                            warnings=list(blockers),
                            **provenance,
                    ),
                    target_unit=resolved.unit,
                )
                )
                result.matched_count += 1
                continue
            status, suggestions = _remap_suggestions(
                saved,
                by_name,
                by_code,
                raw_supplier_name,
                products,
                suggestion_pool_limit,
            )
            result.candidates.append(
                UpdateCandidate(
                    candidate_id=candidate_id,
                    row_number=None,
                    pioneers_code=None,
                    pioneers_name=None,
                    supplier_code=item.supplier_code,
                    supplier_name=raw_supplier_name,
                    old_price=None,
                    new_price=new_price,
                    absolute_change=None,
                    percentage_change=None,
                    match_type=MappingType.SAVED_MAPPING,
                    status=status,
                    review_decision=ReviewDecision.EXCLUDE,
                    warnings=[SAVED_TARGET_UNRESOLVED_WARNING, *blockers],
                    suggestions=suggestions,
                    **provenance,
                )
            )
            if status is MatchStatus.AMBIGUOUS:
                result.ambiguous_count += 1
            else:
                result.unmatched_count += 1
            continue

        # 2) Exact normalized name
        exact_hits = by_name.get(supplier_name, [])
        if len(exact_hits) == 1:
            product = exact_hits[0]
            absolute, _, percentage = _price_fields(product.sale_price, new_price)
            result.candidates.append(
                apply_sale_compatibility(
                    UpdateCandidate(
                        candidate_id=candidate_id,
                        row_number=product.row_number,
                        pioneers_code=product.code,
                        pioneers_name=product.name,
                        supplier_code=item.supplier_code,
                        supplier_name=raw_supplier_name,
                        old_price=product.sale_price,
                        new_price=new_price,
                        absolute_change=absolute,
                        percentage_change=percentage,
                        match_type=MappingType.EXACT_NAME,
                        status=MatchStatus.MATCHED,
                        review_decision=ReviewDecision.INCLUDE,
                        warnings=list(blockers),
                        **provenance,
                    ),
                    target_unit=product.unit,
                )
            )
            result.matched_count += 1
            continue

        if len(exact_hits) > 1:
            suggestions = [
                {
                    "row_number": p.row_number,
                    "pioneers_code": p.code,
                    "pioneers_name": p.name,
                    "sale_price": str(p.sale_price)
                    if p.sale_price is not None
                    else None,
                    "score": 1.0,
                }
                for p in exact_hits[:suggestion_pool_limit]
            ]
            result.candidates.append(
                UpdateCandidate(
                    candidate_id=candidate_id,
                    row_number=None,
                    pioneers_code=None,
                    pioneers_name=None,
                    supplier_code=item.supplier_code,
                    supplier_name=raw_supplier_name,
                    old_price=None,
                    new_price=new_price,
                    absolute_change=None,
                    percentage_change=None,
                    match_type=None,
                    status=MatchStatus.AMBIGUOUS,
                    review_decision=ReviewDecision.EXCLUDE,
                    warnings=[
                        f"normalized name matches {len(exact_hits)} Pioneers products",
                        *blockers,
                    ],
                    suggestions=suggestions,
                    **provenance,
                )
            )
            result.ambiguous_count += 1
            continue

        # 3) Fuzzy suggestions only — never auto-confirm
        suggestions = _suggestion_payloads(
            raw_supplier_name, products, limit=suggestion_pool_limit
        )
        status = MatchStatus.AMBIGUOUS if suggestions else MatchStatus.UNMATCHED
        result.candidates.append(
            UpdateCandidate(
                candidate_id=candidate_id,
                row_number=None,
                pioneers_code=None,
                pioneers_name=None,
                supplier_code=item.supplier_code,
                supplier_name=raw_supplier_name,
                old_price=None,
                new_price=new_price,
                absolute_change=None,
                percentage_change=None,
                match_type=None,
                status=status,
                review_decision=ReviewDecision.EXCLUDE,
                warnings=list(blockers),
                suggestions=suggestions,
                **provenance,
            )
        )
        if status == MatchStatus.AMBIGUOUS:
            result.ambiguous_count += 1
        else:
            result.unmatched_count += 1

    return result


def _suggestion_from_product(
    product: PioneersProduct, *, score: float
) -> dict[str, object]:
    return {
        "row_number": product.row_number,
        "pioneers_code": product.code,
        "pioneers_name": product.name,
        "sale_price": str(product.sale_price) if product.sale_price is not None else None,
        "score": score,
    }


def _remap_suggestions(
    saved: SavedNameMapping,
    by_name: dict[str, list[PioneersProduct]],
    by_code: dict[str, list[PioneersProduct]],
    supplier_name: str,
    products: Sequence[PioneersProduct],
    limit: int,
) -> tuple[MatchStatus, list[dict[str, object]]]:
    """Suggestions for a saved mapping that must be confirmed again.

    Nothing here is selected automatically.
    """
    suggestions: list[dict[str, object]] = []
    seen_rows: set[int] = set()

    def add(product: PioneersProduct, score: float) -> None:
        if product.row_number in seen_rows or len(suggestions) >= limit:
            return
        seen_rows.add(product.row_number)
        suggestions.append(_suggestion_from_product(product, score=score))

    if saved.pioneers_code:
        for product in by_code.get(saved.pioneers_code, []):
            add(product, 1.0)
    for product in by_name.get(saved.pioneers_name_normalized, []):
        add(product, 1.0)
    if not suggestions:
        for payload in _suggestion_payloads(supplier_name, products, limit=limit):
            suggestions.append(payload)
    status = MatchStatus.AMBIGUOUS if suggestions else MatchStatus.UNMATCHED
    return status, suggestions


def _resolve_saved_mapping(
    saved: SavedNameMapping,
    by_name: dict[str, list[PioneersProduct]],
    by_code: dict[str, list[PioneersProduct]],
) -> PioneersProduct | None:
    """Verify a saved mapping still points to exactly one current product."""
    hits = by_name.get(saved.pioneers_name_normalized, [])
    if saved.pioneers_code:
        code_hits = by_code.get(saved.pioneers_code, [])
        if len(code_hits) == 1:
            product = code_hits[0]
            # Name must still agree when both are present.
            if normalize_product_name(product.name) == saved.pioneers_name_normalized:
                return product
            # Code exists but name changed — unsafe.
            return None
        if len(code_hits) > 1:
            return None
        # Code missing from current workbook — try name only.
    if len(hits) == 1:
        return hits[0]
    return None


def search_pioneers_products(
    products: Sequence[PioneersProduct],
    query: str,
    *,
    limit: int = 25,
) -> list[PioneersProduct]:
    """Simple substring / similarity search for manual matching UI."""
    q = query.strip()
    if not q:
        return []
    q_norm = normalize_product_name(q)
    scored: list[tuple[float, PioneersProduct]] = []
    for product in products:
        name_norm = normalize_product_name(product.name)
        code = product.code or ""
        if (
            q_norm in name_norm
            or (code and q in code)
            or (code and q_norm == normalize_product_name(code))
        ):
            score = 1.0 if q_norm == name_norm else 0.85
        else:
            score = name_similarity(q, product.name)
            if score < 0.25:
                continue
        scored.append((score, product))
    scored.sort(key=lambda pair: (-pair[0], pair[1].name))
    return [p for _, p in scored[:limit]]
