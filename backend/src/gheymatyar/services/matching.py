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
from gheymatyar.suppliers.base import BaseSupplierProcessor


@dataclass(frozen=True)
class SavedNameMapping:
    """A previously confirmed supplier→Pioneers name mapping."""

    supplier_name_normalized: str
    pioneers_name_raw: str
    pioneers_name_normalized: str
    pioneers_code: str | None = None


@dataclass
class MatchResult:
    candidates: list[UpdateCandidate] = field(default_factory=list)
    matched_count: int = 0
    unmatched_count: int = 0
    ambiguous_count: int = 0


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


def match_supplier_items(
    items: Sequence[SupplierPriceItem],
    products: Sequence[PioneersProduct],
    *,
    processor: BaseSupplierProcessor,
    saved_mappings: Iterable[SavedNameMapping] = (),
    suggestion_pool_limit: int = 8,
) -> MatchResult:
    """Match supplier items to Pioneers products by name.

    Priority:
    1. Saved supplier-specific mapping (verified against current workbook)
    2. Unique exact normalized-name match
    3. Similar-name suggestions → AMBIGUOUS / UNMATCHED (never auto-confirmed)
    """
    by_name = _index_by_normalized_name(products)
    by_code: dict[str, list[PioneersProduct]] = {}
    for product in products:
        if product.code:
            by_code.setdefault(product.code, []).append(product)

    saved_by_supplier_name = {
        m.supplier_name_normalized: m for m in saved_mappings
    }

    result = MatchResult()

    for item in items:
        supplier_name = processor.normalize_supplier_name(item.supplier_name)
        raw_supplier_name = item.supplier_name
        new_price = processor.calculate_final_sale_price(item)
        candidate_id = str(uuid4())

        # 1) Saved mapping
        saved = saved_by_supplier_name.get(supplier_name)
        if saved is not None:
            resolved = _resolve_saved_mapping(saved, by_name, by_code)
            if resolved is not None:
                absolute, _, percentage = _price_fields(
                    resolved.sale_price, new_price
                )
                result.candidates.append(
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
                        warnings=[],
                    )
                )
                result.matched_count += 1
                continue
            # Saved mapping no longer resolves uniquely — fall through.

        # 2) Exact normalized name
        exact_hits = by_name.get(supplier_name, [])
        if len(exact_hits) == 1:
            product = exact_hits[0]
            absolute, _, percentage = _price_fields(product.sale_price, new_price)
            result.candidates.append(
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
                    warnings=[],
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
                        f"normalized name matches {len(exact_hits)} Pioneers products"
                    ],
                    suggestions=suggestions,
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
                warnings=[],
                suggestions=suggestions,
            )
        )
        if status == MatchStatus.AMBIGUOUS:
            result.ambiguous_count += 1
        else:
            result.unmatched_count += 1

    return result


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
