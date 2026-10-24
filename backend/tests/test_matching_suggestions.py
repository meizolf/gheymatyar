"""Fuzzy suggestions: cached Pioneers name tokens give the original results."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

import gheymatyar.services.matching as matching
import gheymatyar.services.name_normalization as name_normalization
from gheymatyar.domain.product import PioneersProduct
from gheymatyar.domain.supplier_item import SupplierPriceItem
from gheymatyar.parsers.pioneers_excel_parser import PioneersExcelParser
from gheymatyar.services.matching import (
    SavedNameMapping,
    item_decision_identities,
    match_supplier_items,
)
from gheymatyar.services.name_normalization import name_similarity
from gheymatyar.suppliers.registry import get_default_registry

from .conftest import AZIN_PDF, DINA_PDF, KIAN_PDF, NEWPIPE_PDF, PIONEERS_AZIN


def _reference_payloads(
    supplier_name: str,
    products,
    *,
    product_tokens=None,
    limit: int = 5,
    min_score: float = 0.35,
) -> list[dict[str, object]]:
    """The suggestion code before tokens were cached, kept as the oracle."""
    del product_tokens
    scored = []
    for product in products:
        score = name_similarity(supplier_name, product.name)
        if score >= min_score:
            scored.append((score, product))
    scored.sort(key=lambda pair: (-pair[0], pair[1].name))
    return [
        {
            "row_number": product.row_number,
            "pioneers_code": product.code,
            "pioneers_name": product.name,
            "sale_price": str(product.sale_price)
            if product.sale_price is not None
            else None,
            "score": round(score, 4),
        }
        for score, product in scored[:limit]
    ]


def _comparable(result) -> list[tuple[object, ...]]:
    # candidate_id is a fresh uuid4 on every run.
    return [
        (
            c.status,
            c.row_number,
            c.match_type,
            c.review_decision,
            c.new_price,
            tuple(c.warnings),
            tuple(tuple(sorted(s.items())) for s in c.suggestions),
        )
        for c in result.candidates
    ]


def _unresolved_saved_mappings(processor, items) -> list[SavedNameMapping]:
    """Saved mappings whose target is gone, so remapping falls back to fuzzy."""
    saved = []
    for item in items[:5]:
        saved.append(
            SavedNameMapping(
                supplier_name_normalized=processor.normalize_supplier_name(
                    item.supplier_name
                ),
                pioneers_name_raw="محصول حذف شده",
                pioneers_name_normalized="محصول حذف شده",
                pioneers_code="no-such-code",
                identity_key=item_decision_identities(processor, item)[0],
                supplier_code=item.supplier_code,
                unit_normalized=item.unit,
            )
        )
    return saved


@pytest.fixture(scope="module")
def azin_products() -> list[PioneersProduct]:
    if not PIONEERS_AZIN.is_file():
        pytest.skip(f"missing Pioneers azin subset: {PIONEERS_AZIN}")
    return list(PioneersExcelParser().parse(PIONEERS_AZIN).products)


@pytest.mark.parametrize(
    ("supplier_key", "pdf"),
    [
        ("azin_pipe", AZIN_PDF),
        ("newpipe", NEWPIPE_PDF),
        ("dina_polymer", DINA_PDF),
        ("kian", KIAN_PDF),
    ],
)
def test_cached_tokens_match_original_suggestions(
    supplier_key: str,
    pdf: Path,
    azin_products: list[PioneersProduct],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if not pdf.is_file():
        pytest.skip(f"missing supplier PDF fixture: {pdf}")
    processor = get_default_registry().get(supplier_key)
    items = list(processor.parse_pdf(pdf).items)
    saved = _unresolved_saved_mappings(processor, items)
    # Near-miss names for this list, so every supplier gets fuzzy suggestions
    # and not only the Azin rows of the Pioneers subset.
    next_row = max(p.row_number for p in azin_products) + 1
    products = azin_products + [
        PioneersProduct(
            row_number=next_row + index,
            code=f"near-{index}",
            name=f"{item.supplier_name} انبار",
            sale_price=Decimal("1000"),
        )
        for index, item in enumerate(items[:40])
    ]

    current = match_supplier_items(
        items, products, processor=processor, saved_mappings=saved
    )
    monkeypatch.setattr(matching, "_suggestion_payloads", _reference_payloads)
    original = match_supplier_items(
        items, products, processor=processor, saved_mappings=saved
    )

    assert any(c.suggestions for c in current.candidates)
    assert _comparable(current) == _comparable(original)


def test_fuzzy_suggestions_normalize_each_pioneers_name_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    products = [
        PioneersProduct(
            row_number=row,
            code=str(1000 + row),
            name=f"شیر فلکه برنجی {row}",
            sale_price=Decimal("1000"),
        )
        for row in range(2, 302)
    ]
    items = [
        SupplierPriceItem(
            supplier_id="azin_pipe",
            supplier_code=str(5000 + index),
            supplier_name=f"شیر فلکه برنجی کد {index}",
            price=Decimal("2000"),
        )
        for index in range(50)
    ]
    calls = 0
    original = name_normalization.normalize_product_name

    def counting(name: str) -> str:
        nonlocal calls
        calls += 1
        return original(name)

    # name_similarity resolves normalize_product_name in its own module.
    monkeypatch.setattr(name_normalization, "normalize_product_name", counting)
    monkeypatch.setattr(matching, "normalize_product_name", counting)
    processor = get_default_registry().get("azin_pipe")

    result = match_supplier_items(items, products, processor=processor)

    assert all(c.suggestions for c in result.candidates)
    # Index + token cache per product, a few calls per item. Normalizing per
    # comparison would be about 2 * 300 * 50 = 30,000 calls.
    assert calls <= 2 * len(products) + 10 * len(items)
