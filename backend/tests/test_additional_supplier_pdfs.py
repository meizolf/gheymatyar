"""Extraction tests for TOP, Dina, NewPipe, and Abrahan price lists."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from gheymatyar.domain.enums import ReviewDecision
from gheymatyar.domain.product import PioneersProduct
from gheymatyar.services.matching import match_supplier_items
from gheymatyar.services.name_normalization import normalize_product_name
from gheymatyar.services.price_validation import apply_price_warnings, is_exportable
from gheymatyar.suppliers.abrahan_pipe import AbrahanPipeProcessor
from gheymatyar.suppliers.dina_polymer import DinaPolymerProcessor
from gheymatyar.suppliers.newpipe import NewPipeProcessor
from gheymatyar.suppliers.registry import get_default_registry
from gheymatyar.suppliers.textutil import parse_grouped_amount
from gheymatyar.suppliers.top_industrial import TopIndustrialProcessor


@pytest.fixture(scope="module")
def top_result(top_pdf: Path):
    return TopIndustrialProcessor().parse_pdf(top_pdf)


@pytest.fixture(scope="module")
def dina_result(dina_pdf: Path):
    return DinaPolymerProcessor().parse_pdf(dina_pdf)


@pytest.fixture(scope="module")
def newpipe_result(newpipe_pdf: Path):
    return NewPipeProcessor().parse_pdf(newpipe_pdf)


@pytest.fixture(scope="module")
def abrahan_result(abrahan_pdf: Path):
    return AbrahanPipeProcessor().parse_pdf(abrahan_pdf)


def _by_code(result, code: str):
    return next(item for item in result.items if item.supplier_code == code)


def _abrahan_row(result, row: str):
    return next(
        item
        for item in result.items
        if str(item.raw_values.get("source_row_number")) == row
        and item.raw_values.get("page") == 1
    )


def test_parse_grouped_amount_rejects_ambiguous_separators() -> None:
    assert parse_grouped_amount("۱,۷۶۹,۰۰۰") == Decimal("1769000")
    assert parse_grouped_amount("3.240.000") == Decimal("3240000")
    assert parse_grouped_amount("1,234.567") is None
    assert parse_grouped_amount("140") is None
    assert parse_grouped_amount("موجود") is None


def test_registry_lists_text_suppliers_only() -> None:
    keys = set(get_default_registry().keys())
    assert {
        "azin_pipe",
        "top_industrial",
        "dina_polymer",
        "newpipe",
        "abrahan_pipe",
    } <= keys
    assert "pars_plast" not in keys
    assert "kaveh_gostar" not in keys
    assert "polymer_golpayegan" not in keys


def test_api_lists_new_suppliers(client) -> None:
    body = client.get("/api/suppliers").json()
    keys = {item["key"] for item in body}
    assert "top_industrial" in keys
    assert "dina_polymer" in keys
    assert "newpipe" in keys
    assert "abrahan_pipe" in keys
    assert "pars_plast" not in keys


def test_top_extracts_printed_toman_prices(top_result) -> None:
    assert len(top_result.items) == 128
    paris = next(item for item in top_result.items if item.supplier_name == "تاپ فلاش تانک پاریس")
    assert paris.price == Decimal("3240000")
    assert paris.raw_values["original_currency"] == "toman"
    assert paris.raw_values["currency"] == "rial"
    assert paris.raw_values["price_basis"] == "piece"
    assert paris.raw_values["package_quantity"] == "5"
    assert paris.raw_values["page"] == 1
    assert paris.price != Decimal("32400000")
    assert paris.raw_values["pricing_blockers"] == []

    oscar = next(item for item in top_result.items if item.supplier_name == "تاپ فلاش تانک اسکار")
    assert oscar.price == Decimal("3000000")

    sink = next(item for item in top_result.items if item.supplier_code == "216")
    assert sink.price == Decimal("510000")
    assert "سیفون روشویی" in sink.supplier_name
    assert sink.raw_values["package_quantity"] == "40"

    floor = next(item for item in top_result.items if item.supplier_code == "501")
    assert floor.price == Decimal("182000")
    assert "15" in floor.supplier_name
    assert floor.raw_values["package_quantity"] == "80"

    elbow = next(item for item in top_result.items if item.supplier_name == "تاپ زانو 90 درجه")
    assert elbow.price == Decimal("127000")
    assert elbow.raw_values["package_quantity"] == "120"
    assert elbow.raw_values["page"] == 2

    flex = next(item for item in top_result.items if item.supplier_code == "311")
    assert flex.price == Decimal("114000")
    assert flex.raw_values["page"] == 7


def test_top_converts_toman_to_rial_for_export(top_result) -> None:
    processor = TopIndustrialProcessor()
    item = next(row for row in top_result.items if row.supplier_name == "تاپ فلاش تانک پاریس")
    # 3,240,000 Toman → 32,400,000 Rial; carton qty 5 is not multiplied.
    assert processor.calculate_final_sale_price(item) == Decimal("32400000")
    assert processor.calculate_final_sale_price(item) != item.price * 5
    product = PioneersProduct(
        row_number=2,
        name=item.supplier_name,
        code="T-1",
        sale_price=Decimal("24100000"),
        unit="عدد",
    )
    matched = match_supplier_items(
        [item],
        [product],
        processor=processor,
    )
    enriched = apply_price_warnings(matched.candidates)
    assert enriched[0].status == "MATCHED"
    assert enriched[0].new_price == Decimal("32400000")
    assert enriched[0].source_currency == "rial"
    assert enriched[0].pricing_blockers == []
    assert is_exportable(enriched[0]) is False  # soft suspicious-% warning
    approved = enriched[0].model_copy(
        update={"review_decision": ReviewDecision.APPROVE}
    )
    assert is_exportable(approved) is True


def test_dina_keeps_per_meter_prices_and_piece_fittings(dina_result) -> None:
    assert len(dina_result.items) == 384
    pipe = _by_code(dina_result, "825331050")
    assert pipe.price == Decimal("909370")
    assert pipe.price != Decimal("909370") * 6
    assert pipe.raw_values["price_basis"] == "meter"
    assert pipe.raw_values["currency"] == "rial"
    assert pipe.raw_values["package_length_m"] == "6"
    assert pipe.unit == "متر"
    assert "PE80" in pipe.supplier_name
    assert "SDR 33" in pipe.supplier_name
    assert pipe.raw_values["page"] == 1

    other = _by_code(dina_result, "825332050")
    assert other.price == Decimal("962720")
    assert "PE100" in other.supplier_name
    assert "5 bar" in other.supplier_name

    irrigation = _by_code(dina_result, "825164100")
    assert irrigation.price == Decimal("169510")
    assert irrigation.raw_values["pressure_bar"] == "4"
    assert irrigation.raw_values["package_length_m"] == "100"
    assert irrigation.price != Decimal("169510") * 100

    drip = _by_code(dina_result, "825952020")
    assert drip.price == Decimal("198440")
    assert drip.raw_values["drip_spacing_cm"] == "20"
    assert drip.raw_values["ignored_column"] == "188100"
    assert drip.price != Decimal("188100")

    sewage = _by_code(dina_result, "831125050")
    assert sewage.price == Decimal("1435280")
    assert "فاضلابی" in sewage.supplier_name
    assert sewage.raw_values["page"] == 4

    tee = _by_code(dina_result, "855441118")
    assert tee.price == Decimal("67760")
    assert tee.raw_values["price_basis"] == "piece"
    assert tee.raw_values["price_column"] == "#N/A"
    assert "سه راهی" in tee.supplier_name
    assert tee.raw_values["review_warnings"] == []
    assert tee.raw_values["pricing_blockers"] == []

    elbow = _by_code(dina_result, "855441110")
    assert elbow.price == Decimal("68090")
    assert "زانو" in elbow.supplier_name
    assert elbow.raw_values["price_basis"] == "piece"


def test_dina_fitting_na_column_is_exportable_rial_price(dina_result) -> None:
    item = _by_code(dina_result, "855441118")
    assert item.price == Decimal("67760")
    product = PioneersProduct(
        row_number=4,
        name=item.supplier_name,
        code="D-1",
        sale_price=item.price,
        unit="عدد",
    )
    matched = match_supplier_items(
        [item],
        [product],
        processor=DinaPolymerProcessor(),
    )
    enriched = apply_price_warnings(matched.candidates)
    assert enriched[0].status == "MATCHED"
    assert enriched[0].pricing_blockers == []
    assert enriched[0].new_price == Decimal("67760")
    assert is_exportable(enriched[0]) is True


def test_dina_drip_uses_gheymat_not_adjacent_na(dina_result) -> None:
    drip = _by_code(dina_result, "825952020")
    assert drip.price == Decimal("198440")
    assert drip.raw_values["price_column"] == "قیمت"
    assert drip.raw_values["ignored_column"] == "188100"
    assert drip.raw_values["secondary_na_column"] == "188100"
    assert drip.price != Decimal("188100")


def test_dina_terminal_rows_keep_their_column_and_branch_length(dina_result) -> None:
    expected = {
        "825211500": ("PE80", "6 bar", "SDR 21", "500", Decimal("114377780")),
        "825211560": ("PE80", "6 bar", "SDR 21", "560", Decimal("143209770")),
        "825211630": ("PE80", "6 bar", "SDR 21", "630", Decimal("180596350")),
        "825091450": ("PE80", "16 bar", "SDR 9", "450", Decimal("200873860")),
        "825091500": ("PE80", "16 bar", "SDR 9", "500", Decimal("247448740")),
        "825091560": ("PE80", "16 bar", "SDR 9", "560", Decimal("310498980")),
    }
    for code, (family, pressure, sdr, size, price) in expected.items():
        item = _by_code(dina_result, code)
        assert item.price == price
        assert family in item.supplier_name
        assert "PE100" not in item.supplier_name
        assert pressure in item.supplier_name
        assert sdr in item.supplier_name
        assert item.raw_values["size"] == size
        assert item.raw_values["package_length_m"] == "12"
        assert "12 متر" in item.supplier_name
        assert item.raw_values["review_warnings"] == []


def test_dina_repeated_drip_descriptors_are_not_auto_exported(dina_result) -> None:
    first = _by_code(dina_result, "825952020")
    second = _by_code(dina_result, "825954020")
    assert first.price == second.price
    assert normalize_product_name(first.supplier_name) == normalize_product_name(
        second.supplier_name
    )
    product = PioneersProduct(
        row_number=2,
        name=first.supplier_name,
        code="DRIP",
        sale_price=first.price,
    )
    matched = match_supplier_items(
        [first, second], [product], processor=DinaPolymerProcessor()
    )
    enriched = apply_price_warnings(matched.candidates)
    assert len(enriched) == 2
    assert all(candidate.pricing_blockers for candidate in enriched)
    assert all(is_exportable(candidate) is False for candidate in enriched)


def test_newpipe_two_column_prices_include_stated_vat(newpipe_result) -> None:
    assert len(newpipe_result.items) == 551
    assert newpipe_result.source_metadata["pricing_rule"] == "direct_replacement_vat_inclusive"
    pipe = _by_code(newpipe_result, "813121016")
    assert pipe.price == Decimal("1244650")
    assert pipe.price != Decimal("1244650") * 200
    assert pipe.raw_values["package_quantity"] == "200"
    assert pipe.raw_values["package_note"] == "رولی"
    assert "پنج لایه" in pipe.supplier_name
    assert "16" in pipe.supplier_name
    assert "رولی" in pipe.supplier_name
    assert pipe.raw_values["tax"] == "included_10_percent"
    assert pipe.raw_values["page"] == 1

    insert = _by_code(newpipe_result, "855121180")
    assert insert.price == Decimal("1899920")
    assert "1/2" in insert.supplier_name
    assert "10mm" in insert.supplier_name
    assert insert.raw_values["column"] == "left"
    assert pipe.raw_values["column"] == "right"

    coupling = _by_code(newpipe_result, "855141102")
    assert coupling.price == Decimal("2222770")
    assert "بوشن پرسی" in coupling.supplier_name
    assert coupling.raw_values["page"] == 2

    valve = _by_code(newpipe_result, "861641102")
    assert valve.price == Decimal("6301130")
    assert "شیر" in valve.supplier_name

    foam = _by_code(newpipe_result, "879371016")
    assert foam.price == Decimal("123860")
    assert "فوم" in foam.supplier_name
    assert foam.raw_values["page"] == 11

    processor = NewPipeProcessor()
    assert processor.calculate_final_sale_price(pipe) == pipe.price


def test_newpipe_keeps_section_headings_and_coil_form(newpipe_result) -> None:
    headed = _by_code(newpipe_result, "855163602")
    assert headed.price == Decimal("12143340")
    assert "سه راهی صفحه دار توپیچ پرسی" in headed.supplier_name

    plain = _by_code(newpipe_result, "855211610")
    plated = _by_code(newpipe_result, "855213610")
    assert plain.price == Decimal("14107390")
    assert plated.price == Decimal("17699440")
    assert "صفحه دار" not in plain.supplier_name
    assert "سه راهی صفحه دار توپیچ کوپلی" in plated.supplier_name
    assert normalize_product_name(plain.supplier_name) != normalize_product_name(
        plated.supplier_name
    )

    coil = _by_code(newpipe_result, "813121041")
    branch = _by_code(newpipe_result, "813121040")
    assert coil.price == branch.price == Decimal("10354520")
    assert "رولی" in coil.supplier_name
    assert "شاخه" in branch.supplier_name
    assert normalize_product_name(coil.supplier_name) != normalize_product_name(
        branch.supplier_name
    )


def test_newpipe_preserves_mixed_fraction_male_female_dimensions(newpipe_result) -> None:
    male_large = _by_code(newpipe_result, "855121244")
    male_small = _by_code(newpipe_result, "855121236")
    mixed = _by_code(newpipe_result, "855121242")

    assert male_large.price == Decimal("5900070")
    assert male_small.price == Decimal("13387770")
    assert mixed.price == Decimal("7837170")

    assert male_large.raw_values["size"] == "روپیچ 1 1/4*توپیچ 1"
    assert male_small.raw_values["size"] == "روپیچ 1*توپیچ 1 1/4"
    assert mixed.raw_values["size"] == "روپیچ 1 1/4*توپیچ 3/4"
    assert "1 1/4" in male_large.supplier_name and "توپیچ 1" in male_large.supplier_name
    assert "روپیچ 1*" in male_small.supplier_name or "روپیچ 1*توپیچ" in male_small.supplier_name
    assert "1 1/4" in male_small.supplier_name
    assert "3/4" in mixed.supplier_name and "1 1/4" in mixed.supplier_name

    assert normalize_product_name(male_large.supplier_name) != normalize_product_name(
        male_small.supplier_name
    )
    assert normalize_product_name(male_large.supplier_name) != normalize_product_name(
        mixed.supplier_name
    )
    assert normalize_product_name(male_small.supplier_name) != normalize_product_name(
        mixed.supplier_name
    )

    # Reciprocal variants match independently and are not collision-blocked.
    products = [
        PioneersProduct(
            row_number=2,
            name=male_large.supplier_name,
            code="NP-A",
            sale_price=male_large.price,
        ),
        PioneersProduct(
            row_number=3,
            name=male_small.supplier_name,
            code="NP-B",
            sale_price=male_small.price,
        ),
    ]
    matched = match_supplier_items(
        [male_large, male_small],
        products,
        processor=NewPipeProcessor(),
    )
    enriched = apply_price_warnings(matched.candidates)
    assert len(enriched) == 2
    assert all(candidate.status == "MATCHED" for candidate in enriched)
    assert all(not candidate.pricing_blockers for candidate in enriched)
    assert all(is_exportable(candidate) is True for candidate in enriched)


def test_newpipe_single_labelled_reducing_caps_keep_distinct_sizes(
    newpipe_result,
) -> None:
    """Page-6 reducing caps: overall size + female only — no invented male label."""
    smaller = _by_code(newpipe_result, "855121936")
    larger = _by_code(newpipe_result, "855121938")

    assert smaller.price == Decimal("7732010")
    assert larger.price == Decimal("8926940")
    assert smaller.raw_values["size"] == "1 1/4*توپیچ 1/2"
    assert larger.raw_values["size"] == "1 1/2*توپیچ 1/2"
    assert "روپیچ" not in (smaller.raw_values["size"] or "")
    assert "روپیچ" not in (larger.raw_values["size"] or "")
    assert smaller.raw_values["pricing_blockers"] == []
    assert larger.raw_values["pricing_blockers"] == []
    assert "1 1/4" in smaller.supplier_name and "توپیچ 1/2" in smaller.supplier_name
    assert "1 1/2" in larger.supplier_name and "توپیچ 1/2" in larger.supplier_name
    assert normalize_product_name(smaller.supplier_name) != normalize_product_name(
        larger.supplier_name
    )

    products = [
        PioneersProduct(
            row_number=2,
            name=smaller.supplier_name,
            code="NP-CAP-A",
            sale_price=smaller.price,
        ),
        PioneersProduct(
            row_number=3,
            name=larger.supplier_name,
            code="NP-CAP-B",
            sale_price=larger.price,
        ),
    ]
    matched = match_supplier_items(
        [smaller, larger],
        products,
        processor=NewPipeProcessor(),
    )
    enriched = apply_price_warnings(matched.candidates)
    assert len(enriched) == 2
    assert all(candidate.status == "MATCHED" for candidate in enriched)
    assert all(not candidate.pricing_blockers for candidate in enriched)
    assert {c.new_price for c in enriched} == {
        Decimal("7732010"),
        Decimal("8926940"),
    }
    assert all(is_exportable(candidate) is True for candidate in enriched)


def test_newpipe_genuine_name_collisions_remain_blocked() -> None:
    """Collision blocker still fires for identical names with different prices."""
    from gheymatyar.domain.supplier_item import SupplierPriceItem

    shared_name = "نیوپایپ تبدیل روپیچ توپیچ روپیچ 1*توپیچ 1"
    left = SupplierPriceItem(
        supplier_id="newpipe",
        supplier_code="COLLIDE-A",
        supplier_name=shared_name,
        price=Decimal("1000"),
        raw_values={
            "currency": "rial",
            "price_basis": "printed",
            "review_warnings": [],
            "pricing_blockers": [],
        },
    )
    right = SupplierPriceItem(
        supplier_id="newpipe",
        supplier_code="COLLIDE-B",
        supplier_name=shared_name,
        price=Decimal("2000"),
        raw_values={
            "currency": "rial",
            "price_basis": "printed",
            "review_warnings": [],
            "pricing_blockers": [],
        },
    )
    product = PioneersProduct(
        row_number=2,
        name=shared_name,
        code="NP",
        sale_price=Decimal("1000"),
    )
    matched = match_supplier_items(
        [left, right], [product], processor=NewPipeProcessor()
    )
    enriched = apply_price_warnings(matched.candidates)
    assert all(candidate.pricing_blockers for candidate in enriched)
    assert all(is_exportable(candidate) is False for candidate in enriched)
    approved = [
        row.model_copy(update={"review_decision": ReviewDecision.APPROVE})
        for row in enriched
    ]
    assert all(is_exportable(row) is False for row in approved)


def test_abrahan_sections_and_package_quantities(abrahan_result) -> None:
    assert len(abrahan_result.items) == 175
    pipe = _abrahan_row(abrahan_result, "1")
    assert pipe.price == Decimal("1769000")
    assert pipe.raw_values["package_quantity"] == "140 متر"
    assert pipe.price != Decimal("140")
    assert "ضخامت بالا" in pipe.supplier_name
    assert pipe.supplier_name.endswith("20")

    fiber = _abrahan_row(abrahan_result, "8")
    assert fiber.price == Decimal("1950000")
    assert "سه لایه" in fiber.supplier_name

    tee = _abrahan_row(abrahan_result, "50")
    assert tee.price == Decimal("5569540")
    assert "63-40-63" in tee.supplier_name
    assert tee.raw_values["package_quantity"] == "15"

    elbow = _abrahan_row(abrahan_result, "52")
    assert elbow.price == Decimal("267300")
    assert "زانو 45 درجه" in elbow.supplier_name
    assert elbow.raw_values["package_quantity"] == "300"

    bush = _abrahan_row(abrahan_result, "13")
    assert bush.price == Decimal("204600")
    assert "بوشن" in bush.supplier_name

    page2 = next(
        item
        for item in abrahan_result.items
        if item.raw_values.get("page") == 2
        and str(item.raw_values.get("source_row_number")) == "174"
    )
    assert page2.price == Decimal("271040")
    assert "شیر" in page2.supplier_name
    assert any("موجود" in warning for warning in abrahan_result.warnings)
    assert all(item.price != Decimal("176") for item in abrahan_result.items)


def test_ambiguous_supplier_name_is_not_auto_confirmed(abrahan_result) -> None:
    item = _abrahan_row(abrahan_result, "52")
    products = [
        PioneersProduct(
            row_number=2,
            name=item.supplier_name,
            code="A",
            sale_price=Decimal("100"),
        ),
        PioneersProduct(
            row_number=3,
            name=f"  {item.supplier_name}  ",
            code="B",
            sale_price=Decimal("200"),
        ),
    ]
    matched = match_supplier_items(
        [item], products, processor=AbrahanPipeProcessor()
    )
    assert matched.ambiguous_count == 1
    assert matched.candidates[0].status == "AMBIGUOUS"
    enriched = apply_price_warnings(matched.candidates)
    assert is_exportable(enriched[0]) is False
