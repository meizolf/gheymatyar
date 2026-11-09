"""Sahargas (one page, five tables) and Texa (three pages) price lists.

Each PDF is parsed once per module. Expected prices were read off the
rendered pages, one cell at a time.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
import xlrd

from gheymatyar.suppliers.registry import get_default_registry
from gheymatyar.suppliers.sahargas import SahargasProcessor
from gheymatyar.suppliers.texa import TexaProcessor

from .conftest import PIONEERS_AZIN, SAHARGAS_PDF, TEXA_PDF

SG = "سحرگاز"
TX = "تکسا "
SUPPLIERS = {
    "sahargas": (SahargasProcessor, SAHARGAS_PDF, 239),
    "texa": (TexaProcessor, TEXA_PDF, 63),
}


@pytest.fixture(scope="module")
def parsed():
    return {key: proc().parse_pdf(pdf) for key, (proc, pdf, _count) in SUPPLIERS.items()}


def _prices(result) -> dict[str, Decimal]:
    return {item.supplier_name: item.price for item in result.items}


@pytest.mark.parametrize(
    ("supplier", "name", "rial"),
    [
        # One elbow size, three constructions: each its own product and column.
        ("sahargas", f"زانو 90 درجه {SG} 1 1/4 اینچ مانیسمان سنگین", 1_663_000),
        ("sahargas", f"زانو 90 درجه {SG} 1 1/4 اینچ درزدار استاندارد", 941_000),
        ("sahargas", f"زانو 90 درجه {SG} 1 1/4 اینچ سبک", 810_000),
        ("sahargas", f"زانو 90 درجه {SG} 1/2 اینچ درزدار استاندارد", 272_000),
        ("sahargas", f"زانو 90 درجه {SG} 12 اینچ سبک", 76_230_000),
        # Size from the code column (4*2.5), not the misprinted «1,1/4" * 3.4"».
        ("sahargas", f"تبدیل استاندارد {SG} 1 1/4×3/4 اینچ مانیسمان ضخامت رده 40", 1_009_000),
        ("sahargas", f"تبدیل استاندارد {SG} 1 1/4×3/4 اینچ درزدار سنگین", 485_000),
        ("sahargas", f"سه راهی مساوی {SG} 2 1/2 اینچ مانیسمان ضخامت رده 40", 9_802_000),
        ("sahargas", f"سه راهی تبدیلی {SG} 4×3 اینچ درزدار سنگین", 7_943_000),
        ("sahargas", f"سردنده {SG} 4 اینچ درزدار 8 و 10 CM", 2_780_000),
        ("sahargas", f"کپ استاندارد {SG} 10 اینچ سبک ضخامت 3 میل", 7_496_000),
        # «/» thousands; code 700 names two different products.
        ("texa", TX + "شیر شوفاژ", 10_970_000),
        ("texa", TX + "شیر و زانو شوفاژ", 19_100_000),
        ("texa", TX + 'شیر پکیج 1" اکونومی', 14_980_000),  # printed «پیکج»
        ("texa", TX + "صافی 3/4 روپیچ توپیچ", 9_470_000),
        ("texa", TX + 'شیر حیاطی 1"', 21_590_000),  # row without a row number
        ("texa", TX + 'شیر یک طرفه فنری 1" سوپاپ برنجی', 15_960_000),  # unmapped glyphs
        ("texa", TX + 'فلوتر 1 1/4" سوپاپ برنجی', 41_320_000),  # stacked fraction
        ("texa", TX + "فلوتر 3/4 سوپاپ ABS", 11_080_000),
        ("texa", TX + "مهره واسطه کد 700", 3_540_000),  # page 3 spare parts
    ],
)
def test_names_and_rial_prices(parsed, supplier, name, rial) -> None:
    assert _prices(parsed[supplier]).get(name) == Decimal(rial), name


@pytest.mark.parametrize("supplier", list(SUPPLIERS))
def test_counts_rial_unique_names_and_detection(parsed, supplier) -> None:
    processor, pdf, count = SUPPLIERS[supplier]
    items = parsed[supplier].items
    assert len(items) == count
    normalized = {processor().normalize_supplier_name(i.supplier_name) for i in items}
    assert len(normalized) == count  # matching keys stay distinct
    assert all(i.price > 0 and i.price == i.price.to_integral() for i in items)
    assert {(i.raw_values["currency"], i.raw_values["price_basis"]) for i in items} == {
        ("rial", "printed")
    }
    assert get_default_registry().detect(pdf).detected_supplier_id == supplier


def test_unpriced_cells_are_skipped_not_guessed(parsed) -> None:
    sahargas = _prices(parsed["sahargas"])
    for name in (
        f"زانو 90 درجه {SG} 1/2 اینچ سبک",  # printed 0
        f"زانو 90 درجه {SG} 12 اینچ مانیسمان سنگین",  # توافقی
        f"تبدیل استاندارد {SG} 12×10 اینچ درزدار سنگین",  # توافقی
    ):
        assert name not in sahargas
    assert not any("مختلف" in name for name in sahargas)  # zero-priced tees
    texa = parsed["texa"]
    assert not any(i.supplier_code == "890" for i in texa.items)  # dashed price
    assert any("code 890" in w for w in texa.warnings)
    assert sorted(i.supplier_name for i in texa.items if i.supplier_code == "700") == [
        TX + "شیر شوفاژ", TX + "شیر و زانو شوفاژ"
    ]


def test_texa_shared_code_maps_saves_and_exports_as_two_products(client) -> None:
    sid = client.post("/api/sessions").json()["session_id"]
    with PIONEERS_AZIN.open("rb") as handle:
        assert client.post(f"/api/sessions/{sid}/pioneers-excel",
                           files={"file": ("p.xlsx", handle, "application/octet-stream")}).status_code == 200
    with TEXA_PDF.open("rb") as handle:
        uploaded = client.post(f"/api/sessions/{sid}/supplier-pdf", data={"supplier_key": "texa"},
                               files={"file": ("texa.pdf", handle, "application/pdf")})
    assert uploaded.status_code == 200, uploaded.text
    candidates = client.post(f"/api/sessions/{sid}/match").json()["candidates"]
    assert len(candidates) == 63
    shared = sorted((c for c in candidates if c["supplier_code"] == "700"),
                    key=lambda c: c["new_price"])
    session = client.app.state.processing.get_session(sid)
    free = [p for p in session.products if p.code and p.code not in session.duplicate_codes][:2]
    for candidate, product in zip(shared, free):
        url = f"/api/sessions/{sid}/candidates/{candidate['candidate_id']}"
        confirmed = client.post(url + "/confirm-mapping",
                                json={"pioneers_row_number": product.row_number, "save": True})
        assert confirmed.status_code == 200, confirmed.text
        if confirmed.json()["approval"] == "required":
            assert client.post(url + "/review", json={"decision": "APPROVE"}).status_code == 200
    # A third product cannot take a Pioneers product already held.
    third = next(c for c in candidates if c["supplier_code"] == "710")
    held = client.post(f"/api/sessions/{sid}/candidates/{third['candidate_id']}/confirm-mapping",
                       json={"pioneers_row_number": free[0].row_number, "save": True})
    assert held.status_code == 409, held.text

    rematched = client.post(f"/api/sessions/{sid}/match").json()["candidates"]
    saved = {c["supplier_name"]: (c["match_type"], c["pioneers_code"])
             for c in rematched if c["supplier_code"] == "700"}
    assert saved == {
        TX + "شیر شوفاژ": ("SAVED_MAPPING", free[0].code),
        TX + "شیر و زانو شوفاژ": ("SAVED_MAPPING", free[1].code),
    }
    for c in rematched:
        if c["supplier_code"] == "700" and c["approval"] == "required":
            client.post(f"/api/sessions/{sid}/candidates/{c['candidate_id']}/review",
                        json={"decision": "APPROVE"})
    exported = client.post(f"/api/sessions/{sid}/export")
    assert exported.status_code == 200, exported.text
    sheet = xlrd.open_workbook(
        file_contents=client.get(f"/api/sessions/{sid}/download").content
    ).sheet_by_index(0)
    rows = {sheet.cell_value(r, 0): sheet.cell_value(r, 2) for r in range(1, sheet.nrows)}
    assert rows == {free[0].code: 10_970_000, free[1].code: 19_100_000}
