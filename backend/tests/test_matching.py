"""Name-based matching and saved-mapping reuse tests."""

from __future__ import annotations

from decimal import Decimal

from gheymatyar.domain.enums import MappingType, MatchStatus, ReviewDecision
from gheymatyar.domain.product import PioneersProduct
from gheymatyar.domain.supplier_item import SupplierPriceItem
from gheymatyar.services.matching import (
    LEGACY_VARIANT_AMBIGUOUS_WARNING,
    SAVED_TARGET_UNRESOLVED_WARNING,
    SavedNameMapping,
    match_supplier_items,
)
from gheymatyar.services.product_identity import supplier_product_identity
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
    assert result.candidates[0].pioneers_code is None
    assert result.candidates[0].row_number is None
    assert SAVED_TARGET_UNRESOLVED_WARNING in result.candidates[0].warnings


def test_saved_mapping_does_not_fall_through_to_a_different_exact_name() -> None:
    """A missing saved target must not silently select another Pioneers product."""
    products = [
        _product(row_number=2, code="EXACT", name="اذین لوله تک لایه 20"),
    ]
    items = [_item(supplier_name="اذین لوله تک لایه 20")]
    saved = [
        SavedNameMapping(
            supplier_name_normalized=normalize_product_name("اذین لوله تک لایه 20"),
            pioneers_name_raw="اذین لوله 20",
            pioneers_name_normalized=normalize_product_name("اذین لوله 20"),
            pioneers_code="MISSING",
        )
    ]
    result = match_supplier_items(
        items, products, processor=AzinPipeProcessor(), saved_mappings=saved
    )
    assert result.matched_count == 0
    assert result.candidates[0].pioneers_code is None
    assert result.candidates[0].match_type is MappingType.SAVED_MAPPING
    assert SAVED_TARGET_UNRESOLVED_WARNING in result.candidates[0].warnings


def test_saved_mapping_beats_exact_name_of_a_different_product() -> None:
    products = [
        _product(row_number=2, code="EXACT", name="اذین لوله تک لایه 20"),
        _product(row_number=3, code="SAVED", name="اذین لوله 20"),
    ]
    items = [_item(supplier_name="اذین لوله تک لایه 20")]
    saved = [
        SavedNameMapping(
            supplier_name_normalized=normalize_product_name("اذین لوله تک لایه 20"),
            pioneers_name_raw="اذین لوله 20",
            pioneers_name_normalized=normalize_product_name("اذین لوله 20"),
            pioneers_code="SAVED",
        )
    ]
    result = match_supplier_items(
        items, products, processor=AzinPipeProcessor(), saved_mappings=saved
    )
    assert result.candidates[0].match_type is MappingType.SAVED_MAPPING
    assert result.candidates[0].pioneers_code == "SAVED"
    assert result.candidates[0].row_number == 3


def test_ignored_product_is_not_exact_matched() -> None:
    processor = AzinPipeProcessor()
    item = _item(unit="عدد")
    identity = supplier_product_identity(
        normalized_name=processor.normalize_supplier_name(item.supplier_name),
        supplier_code=item.supplier_code,
        unit=item.unit,
    )
    result = match_supplier_items(
        [item],
        [_product(unit="عدد")],
        processor=processor,
        ignored_identities={identity},
    )
    assert result.matched_count == 0
    assert result.ignored_count == 1
    assert result.candidates[0].status is MatchStatus.IGNORED
    assert result.candidates[0].review_decision is ReviewDecision.EXCLUDE
    assert not is_exportable(result.candidates[0])


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
    )
    enriched = apply_price_warnings(result.candidates)
    assert enriched[0].warnings
    assert not is_exportable(enriched[0])
    approved = enriched[0].model_copy(
        update={"review_decision": ReviewDecision.APPROVE}
    )
    assert is_exportable(approved)


def _variant_mapping(
    *,
    code: str,
    unit: str,
    pioneers_code: str,
    pioneers_name: str,
) -> SavedNameMapping:
    normalized = normalize_product_name("کالای مشترک 20")
    return SavedNameMapping(
        supplier_name_normalized=normalized,
        pioneers_name_raw=pioneers_name,
        pioneers_name_normalized=normalize_product_name(pioneers_name),
        pioneers_code=pioneers_code,
        identity_key=supplier_product_identity(
            normalized_name=normalized,
            supplier_code=code,
            unit=unit,
        ),
        supplier_code=code,
        unit_normalized=normalize_product_name(unit),
        legacy_unscoped=False,
    )


def test_variant_mappings_do_not_cross_code_or_unit() -> None:
    products = [
        _product(row_number=2, code="KEEP", name="نگه دار"),
        _product(row_number=3, code="DROP", name="حذف شونده"),
    ]
    saved = [
        _variant_mapping(
            code="VARIANT-A",
            unit="متر",
            pioneers_code="KEEP",
            pioneers_name="نگه دار",
        ),
        _variant_mapping(
            code="VARIANT-B",
            unit="متر",
            pioneers_code="DROP",
            pioneers_name="حذف شونده",
        ),
    ]
    items = [
        _item(supplier_name="کالای مشترک 20", supplier_code="VARIANT-A", unit="متر"),
        _item(supplier_name="کالای مشترک 20", supplier_code="VARIANT-B", unit="متر"),
        _item(supplier_name="کالای مشترک 20", supplier_code="VARIANT-A", unit="شاخه"),
    ]
    result = match_supplier_items(
        items, products, processor=AzinPipeProcessor(), saved_mappings=saved
    )
    by_variant = {
        (candidate.supplier_code, candidate.source_unit): candidate
        for candidate in result.candidates
    }
    assert by_variant[("VARIANT-A", "متر")].pioneers_code == "KEEP"
    assert by_variant[("VARIANT-B", "متر")].pioneers_code == "DROP"
    other = by_variant[("VARIANT-A", "شاخه")]
    assert other.match_type is not MappingType.SAVED_MAPPING
    assert other.pioneers_code not in {"KEEP", "DROP"}


def test_legacy_name_mapping_is_not_applied_to_several_variants() -> None:
    normalized = normalize_product_name("کالای مشترک 20")
    products = [_product(row_number=2, code="EXACT", name="کالای مشترک 20")]
    saved = [
        SavedNameMapping(
            supplier_name_normalized=normalized,
            pioneers_name_raw="کالای مشترک 20",
            pioneers_name_normalized=normalized,
            pioneers_code="EXACT",
            identity_key=supplier_product_identity(normalized_name=normalized),
            legacy_unscoped=True,
        )
    ]
    items = [
        _item(supplier_name="کالای مشترک 20", supplier_code="A", unit="متر"),
        _item(supplier_name="کالای مشترک 20", supplier_code="B", unit="عدد"),
    ]
    result = match_supplier_items(
        items, products, processor=AzinPipeProcessor(), saved_mappings=saved
    )
    assert result.matched_count == 0
    assert len(result.candidates) == 2
    for candidate in result.candidates:
        assert candidate.status is MatchStatus.AMBIGUOUS
        assert candidate.match_type is None
        assert candidate.row_number is None
        assert candidate.review_decision is ReviewDecision.EXCLUDE
        assert LEGACY_VARIANT_AMBIGUOUS_WARNING in candidate.warnings
        assert not is_exportable(candidate)


def test_legacy_name_mapping_is_not_applied_to_one_later_variant() -> None:
    normalized = normalize_product_name("کالای مشترک 20")
    products = [_product(row_number=2, code="EXACT", name="کالای مشترک 20")]
    saved = [
        SavedNameMapping(
            supplier_name_normalized=normalized,
            pioneers_name_raw="کالای مشترک 20",
            pioneers_name_normalized=normalized,
            pioneers_code="EXACT",
            identity_key=supplier_product_identity(normalized_name=normalized),
            legacy_unscoped=True,
        )
    ]
    items = [_item(supplier_name="کالای مشترک 20", supplier_code="ONLY", unit="متر")]
    result = match_supplier_items(
        items, products, processor=AzinPipeProcessor(), saved_mappings=saved
    )
    assert result.matched_count == 0
    candidate = result.candidates[0]
    assert candidate.match_type is None
    assert candidate.status is MatchStatus.AMBIGUOUS
    assert candidate.row_number is None
    assert candidate.pioneers_code is None
    assert LEGACY_VARIANT_AMBIGUOUS_WARNING in candidate.warnings
    assert not is_exportable(candidate)
