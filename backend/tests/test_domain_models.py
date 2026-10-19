"""Unit tests for the Step 2 domain layer."""

from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

from gheymatyar.domain import (
    MappingType,
    MatchStatus,
    PioneersProduct,
    ProductMapping,
    SupplierPriceItem,
    UpdateCandidate,
)


# --- helpers ---


def pioneers(**overrides: object) -> PioneersProduct:
    data: dict[str, object] = {
        "row_number": 2,
        "code": "P-100",
        "name": "Sample Product",
        "barcode": "6260001234567",
        "unit": "عدد",
        "sale_price": Decimal("10000"),
        "last_purchase_price": Decimal("8000"),
        "consumer_price": Decimal("12000"),
        "colleague_price": Decimal("9500"),
        "raw_values": {"A": "P-100"},
    }
    data.update(overrides)
    return PioneersProduct(**data)  # type: ignore[arg-type]


def supplier(**overrides: object) -> SupplierPriceItem:
    data: dict[str, object] = {
        "supplier_id": "sup-1",
        "supplier_code": "S-55",
        "supplier_name": "Supplier Item",
        "barcode": "6260001234567",
        "price": Decimal("11000"),
        "unit": "عدد",
        "raw_values": {"code": "S-55"},
    }
    data.update(overrides)
    return SupplierPriceItem(**data)  # type: ignore[arg-type]


def mapping(**overrides: object) -> ProductMapping:
    data: dict[str, object] = {
        "supplier_id": "sup-1",
        "supplier_name_raw": "Supplier Item",
        "supplier_name_normalized": "supplier item",
        "pioneers_name_raw": "Sample Product",
        "pioneers_name_normalized": "sample product",
        "pioneers_code": "P-100",
        "mapping_type": MappingType.MANUAL,
    }
    data.update(overrides)
    return ProductMapping(**data)  # type: ignore[arg-type]


def candidate(**overrides: object) -> UpdateCandidate:
    data: dict[str, object] = {
        "candidate_id": "c-1",
        "row_number": 2,
        "pioneers_code": "P-100",
        "pioneers_name": "Sample Product",
        "supplier_code": "S-55",
        "supplier_name": "Supplier Item",
        "old_price": Decimal("10000"),
        "new_price": Decimal("11000"),
        "absolute_change": Decimal("1000"),
        "percentage_change": Decimal("10"),
        "match_type": MappingType.EXACT_NAME,
        "status": MatchStatus.MATCHED,
        "warnings": [],
    }
    data.update(overrides)
    return UpdateCandidate(**data)  # type: ignore[arg-type]


# --- PioneersProduct ---


def test_pioneers_product_valid_creation() -> None:
    product = pioneers()
    assert product.row_number == 2
    assert product.code == "P-100"
    assert product.name == "Sample Product"
    assert product.sale_price == Decimal("10000")
    assert product.raw_values == {"A": "P-100"}


def test_pioneers_product_optional_code() -> None:
    product = pioneers(code=None)
    assert product.code is None
    blank = pioneers(code="   ")
    assert blank.code is None


def test_pioneers_product_rejects_blank_name() -> None:
    with pytest.raises(ValidationError):
        pioneers(name="")
    with pytest.raises(ValidationError):
        pioneers(name="  ")


@pytest.mark.parametrize("row_number", [0, -1, -10])
def test_pioneers_product_rejects_non_positive_row_number(row_number: int) -> None:
    with pytest.raises(ValidationError):
        pioneers(row_number=row_number)


def test_pioneers_product_optional_fields_may_be_absent() -> None:
    product = PioneersProduct(row_number=1, name="Only required")
    assert product.code is None
    assert product.barcode is None
    assert product.unit is None
    assert product.sale_price is None
    assert product.last_purchase_price is None
    assert product.consumer_price is None
    assert product.colleague_price is None
    assert product.raw_values == {}


def test_pioneers_product_raw_values_defaults_safely_and_independently() -> None:
    a = PioneersProduct(row_number=1, name="A")
    b = PioneersProduct(row_number=2, name="B")
    a.raw_values["x"] = 1
    assert "x" not in b.raw_values
    assert a.raw_values is not b.raw_values


def test_pioneers_product_decimal_parsing_without_silent_rounding() -> None:
    product = pioneers(
        sale_price="10000.123",
        last_purchase_price=Decimal("8000.456"),
        consumer_price=12000,
        colleague_price=None,
    )
    assert product.sale_price == Decimal("10000.123")
    assert product.last_purchase_price == Decimal("8000.456")
    assert product.consumer_price == Decimal("12000")
    assert product.colleague_price is None


def test_pioneers_product_normalizes_blank_optional_strings() -> None:
    product = pioneers(barcode="  ", unit="\t")
    assert product.barcode is None
    assert product.unit is None


@pytest.mark.parametrize(
    "bad",
    [
        float("nan"),
        Decimal("NaN"),
        Decimal("sNaN"),
        "NaN",
        "nan",
        float("inf"),
        Decimal("Infinity"),
        "-Infinity",
    ],
)
def test_pioneers_product_rejects_non_finite_prices(bad: object) -> None:
    with pytest.raises(ValidationError):
        pioneers(sale_price=bad)


def test_pioneers_product_raw_values_accepts_arbitrary_keys() -> None:
    product = pioneers(raw_values={1: "col-a", "B": 2, ("tuple", "key"): None})
    assert product.raw_values[1] == "col-a"
    assert product.raw_values["B"] == 2
    assert product.raw_values[("tuple", "key")] is None


# --- SupplierPriceItem ---


def test_supplier_price_item_valid_creation() -> None:
    item = supplier()
    assert item.supplier_id == "sup-1"
    assert item.price == Decimal("11000")


def test_supplier_price_item_rejects_blank_supplier_name() -> None:
    with pytest.raises(ValidationError):
        supplier(supplier_name="")
    with pytest.raises(ValidationError):
        supplier(supplier_name="   ")


def test_supplier_price_item_accepts_positive_price() -> None:
    item = supplier(price=Decimal("0.01"))
    assert item.price == Decimal("0.01")


@pytest.mark.parametrize("bad", [0, Decimal("0"), "0", -1, Decimal("-5")])
def test_supplier_price_item_rejects_zero_or_negative_price(bad: object) -> None:
    with pytest.raises(ValidationError):
        supplier(price=bad)


def test_supplier_price_item_optional_supplier_code_accepted() -> None:
    item = SupplierPriceItem(
        supplier_id="sup-1",
        supplier_name="No code",
        price=Decimal("100"),
    )
    assert item.supplier_code is None
    blank = supplier(supplier_code="  ")
    assert blank.supplier_code is None


def test_supplier_price_item_raw_values_defaults_safely_and_independently() -> None:
    a = SupplierPriceItem(
        supplier_id="s", supplier_name="n", price=Decimal("1")
    )
    b = SupplierPriceItem(
        supplier_id="s", supplier_name="n", price=Decimal("1")
    )
    a.raw_values["k"] = "v"
    assert "k" not in b.raw_values


def test_supplier_price_item_rejects_blank_supplier_id() -> None:
    with pytest.raises(ValidationError):
        supplier(supplier_id="")


@pytest.mark.parametrize(
    "bad",
    [
        float("nan"),
        Decimal("NaN"),
        Decimal("sNaN"),
        "NaN",
        float("inf"),
        Decimal("-Infinity"),
    ],
)
def test_supplier_price_item_rejects_non_finite_prices(bad: object) -> None:
    with pytest.raises(ValidationError):
        supplier(price=bad)


def test_supplier_price_item_raw_values_accepts_arbitrary_keys() -> None:
    item = supplier(raw_values={0: "first", "name": "x"})
    assert item.raw_values[0] == "first"
    assert item.raw_values["name"] == "x"


# --- ProductMapping ---


def test_product_mapping_valid() -> None:
    m = mapping()
    assert m.mapping_type is MappingType.MANUAL
    assert m.pioneers_code == "P-100"


@pytest.mark.parametrize("bad", ["", "  ", None])
def test_product_mapping_rejects_blank_supplier_name(bad: object) -> None:
    with pytest.raises(ValidationError):
        mapping(supplier_name_raw=bad)


@pytest.mark.parametrize("bad", ["", "  ", None])
def test_product_mapping_rejects_blank_pioneers_name(bad: object) -> None:
    with pytest.raises(ValidationError):
        mapping(pioneers_name_raw=bad)


def test_product_mapping_optional_pioneers_code() -> None:
    m = mapping(pioneers_code=None)
    assert m.pioneers_code is None
    m2 = mapping(pioneers_code="  ")
    assert m2.pioneers_code is None


@pytest.mark.parametrize(
    "value,expected",
    [
        (MappingType.SAVED_MAPPING, MappingType.SAVED_MAPPING),
        ("EXACT_NAME", MappingType.EXACT_NAME),
        ("MANUAL", MappingType.MANUAL),
    ],
)
def test_product_mapping_accepts_supported_mapping_types(
    value: object, expected: MappingType
) -> None:
    m = mapping(mapping_type=value)
    assert m.mapping_type is expected


@pytest.mark.parametrize("bad", ["barcode", "CODE", "AUTO_CODE", ""])
def test_product_mapping_rejects_unsupported_mapping_types(bad: object) -> None:
    with pytest.raises(ValidationError):
        mapping(mapping_type=bad)


# --- UpdateCandidate ---


def test_update_candidate_valid_creation() -> None:
    c = candidate()
    assert c.status is MatchStatus.MATCHED
    assert c.match_type is MappingType.EXACT_NAME
    assert c.old_price == Decimal("10000")
    assert c.new_price == Decimal("11000")
    assert c.percentage_change == Decimal("10")


def test_update_candidate_required_fields() -> None:
    for field in ("candidate_id", "supplier_name"):
        with pytest.raises(ValidationError):
            candidate(**{field: ""})
        with pytest.raises(ValidationError):
            candidate(**{field: "  "})


def test_update_candidate_optional_identifiers() -> None:
    c = candidate(pioneers_code=None, pioneers_name=None, supplier_code=None)
    assert c.pioneers_code is None
    assert c.pioneers_name is None
    assert c.supplier_code is None


def test_update_candidate_warnings_default_safely_and_independently() -> None:
    a = UpdateCandidate(
        candidate_id="a",
        supplier_name="S",
        old_price=Decimal("0"),
        new_price=Decimal("10"),
        absolute_change=Decimal("10"),
        percentage_change=None,
        match_type=MappingType.MANUAL,
        status=MatchStatus.UNMATCHED,
    )
    b = UpdateCandidate(
        candidate_id="b",
        pioneers_code="P-2",
        pioneers_name="N2",
        supplier_name="S2",
        old_price=Decimal("1"),
        new_price=Decimal("2"),
        absolute_change=Decimal("1"),
        percentage_change=Decimal("100"),
        match_type=MappingType.EXACT_NAME,
        status=MatchStatus.MATCHED,
    )
    assert a.warnings == []
    assert b.warnings == []
    a.warnings.append("w")
    assert b.warnings == []
    assert a.warnings == ["w"]


def test_update_candidate_only_valid_enums() -> None:
    for status in MatchStatus:
        assert candidate(status=status).status is status
    for match_type in MappingType:
        assert candidate(match_type=match_type).match_type is match_type

    with pytest.raises(ValidationError):
        candidate(status="PENDING")
    with pytest.raises(ValidationError):
        candidate(status="approved")
    with pytest.raises(ValidationError):
        candidate(match_type="BARCODE")
    with pytest.raises(ValidationError):
        candidate(match_type="fuzzy")


def test_update_candidate_decimal_values_behave_correctly() -> None:
    c = candidate(
        old_price=Decimal("0"),
        new_price="15.50",
        absolute_change=Decimal("15.50"),
        percentage_change=None,
        status=MatchStatus.AMBIGUOUS,
    )
    assert c.old_price == Decimal("0")
    assert c.new_price == Decimal("15.50")
    assert c.absolute_change == Decimal("15.50")
    assert c.percentage_change is None


def test_update_candidate_accepts_zero_old_price_and_nullable_percentage() -> None:
    c = candidate(
        old_price=0,
        new_price=Decimal("100"),
        absolute_change=Decimal("100"),
        percentage_change=None,
    )
    assert c.old_price == Decimal("0")
    assert c.percentage_change is None


def test_update_candidate_cleans_warning_strings() -> None:
    c = candidate(warnings=["  keep ", "", " also "])
    assert c.warnings == ["keep", "also"]


def test_domain_package_exports() -> None:
    from gheymatyar import domain

    assert set(domain.__all__) == {
        "FinalSalePriceUpdate",
        "MappingType",
        "MatchStatus",
        "PioneersProduct",
        "ProductMapping",
        "ReviewDecision",
        "SupplierPriceItem",
        "UpdateCandidate",
    }
    assert MappingType.EXACT_NAME.value == "EXACT_NAME"
    assert MatchStatus.AMBIGUOUS.value == "AMBIGUOUS"
