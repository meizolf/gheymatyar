"""Name-based matching and saved-mapping reuse tests."""

from __future__ import annotations

from decimal import Decimal

from gheymatyar.domain.enums import MappingType, MatchStatus, ReviewDecision
from gheymatyar.domain.product import PioneersProduct
from gheymatyar.domain.supplier_item import SupplierPriceItem
from gheymatyar.services.matching import SavedNameMapping, match_supplier_items
from gheymatyar.services.name_normalization import normalize_product_name
from gheymatyar.services.price_validation import apply_price_warnings, is_exportable
from gheymatyar.suppliers.azin_pipe import AzinPipeProcessor


def _product(**kwargs: object) -> PioneersProduct:
    data: dict[str, object] = {
        "row_number": 2,
        "code": "100",
        "name": "اذین لوله سه لایه 20",
        "sale_price": Decimal("1000000"),
    }
    data.update(kwargs)
    return PioneersProduct(**data)  # type: ignore[arg-type]


def _item(**kwargs: object) -> SupplierPriceItem:
    data: dict[str, object] = {
        "supplier_id": "azin_pipe",
        "supplier_code": "819121020",
        "supplier_name": "اذین لوله سه لایه 20",
        "price": Decimal("1987040"),
    }
    data.update(kwargs)
    return SupplierPriceItem(**data)  # type: ignore[arg-type]


def test_exact_normalized_name_match() -> None:
    products = [_product()]
    items = [_item(supplier_name="اذین  لوله   سه لایه ۲۰")]
    result = match_supplier_items(items, products, processor=AzinPipeProcessor())
    assert result.matched_count == 1
    assert result.candidates[0].status is MatchStatus.MATCHED
    assert result.candidates[0].match_type is MappingType.EXACT_NAME
    assert result.candidates[0].row_number == 2


def test_saved_mapping_reuse_verified_against_current_workbook() -> None:
    products = [_product(name="اذین لوله 20", code="11307")]
    items = [_item(supplier_name="اذین لوله تک لایه 20")]
    saved = [
        SavedNameMapping(
            supplier_name_normalized=normalize_product_name("اذین لوله تک لایه 20"),
            pioneers_name_raw="اذین لوله 20",
            pioneers_name_normalized=normalize_product_name("اذین لوله 20"),
            pioneers_code="11307",
        )
    ]
    result = match_supplier_items(
        items, products, processor=AzinPipeProcessor(), saved_mappings=saved
    )
    assert result.matched_count == 1
    assert result.candidates[0].match_type is MappingType.SAVED_MAPPING
    assert result.candidates[0].pioneers_code == "11307"


def test_saved_mapping_rejected_when_code_name_conflict() -> None:
    products = [
        _product(row_number=2, code="11307", name="اذین لوله 20 RENAMED"),
    ]
    items = [_item(supplier_name="اذین لوله تک لایه 20")]
    saved = [
        SavedNameMapping(
            supplier_name_normalized=normalize_product_name("اذین لوله تک لایه 20"),
            pioneers_name_raw="اذین لوله 20",
            pioneers_name_normalized=normalize_product_name("اذین لوله 20"),
            pioneers_code="11307",
        )
    ]
    result = match_supplier_items(
        items, products, processor=AzinPipeProcessor(), saved_mappings=saved
    )
    assert result.matched_count == 0
    assert result.candidates[0].status in {
        MatchStatus.UNMATCHED,
        MatchStatus.AMBIGUOUS,
    }


def test_ambiguous_duplicate_normalized_names() -> None:
    products = [
        _product(row_number=2, code="1", name="اذین بوشن 20"),
        _product(row_number=3, code="2", name="اذین بوشن 20"),
    ]
    items = [_item(supplier_name="اذین بوشن 20", supplier_code="855321101")]
    result = match_supplier_items(items, products, processor=AzinPipeProcessor())
    assert result.ambiguous_count == 1
    assert result.candidates[0].status is MatchStatus.AMBIGUOUS
    assert len(result.candidates[0].suggestions) == 2


def test_fuzzy_never_auto_confirmed() -> None:
    products = [_product(name="اذین لوله سه لایه 25")]
    items = [_item(supplier_name="اذین لوله سه لایه 20")]
    result = match_supplier_items(items, products, processor=AzinPipeProcessor())
    assert result.matched_count == 0
    assert result.candidates[0].status in {
        MatchStatus.AMBIGUOUS,
        MatchStatus.UNMATCHED,
    }
    assert result.candidates[0].match_type is None


def test_price_warning_blocks_export_until_approved() -> None:
    products = [_product(sale_price=Decimal("1000000"), unit="عدد")]
    items = [
        _item(
            price=Decimal("2000000"),
            unit="عدد",
            raw_values={"currency": "rial", "price_basis": "piece"},
        )
    ]
    result = match_supplier_items(
        items,
        products,
        processor=AzinPipeProcessor(),
        confirmed_sale_currency="rial",
    )
    enriched = apply_price_warnings(result.candidates)
    assert enriched[0].warnings
    assert not is_exportable(enriched[0])
    approved = enriched[0].model_copy(
        update={"review_decision": ReviewDecision.APPROVE}
    )
    assert is_exportable(approved)
