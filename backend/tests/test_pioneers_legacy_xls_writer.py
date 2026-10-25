"""Approved exports as genuine Excel 97–2003 (BIFF8) ``.xls`` workbooks."""

from __future__ import annotations

import hashlib
import subprocess
import sys
from decimal import Decimal
from pathlib import Path

import pytest
import xlrd
from openpyxl import Workbook

import gheymatyar.services.processing as processing
from gheymatyar.domain.enums import MatchStatus, ReviewDecision
from gheymatyar.domain.update_candidate import UpdateCandidate
from gheymatyar.parsers.pioneers_excel_parser import (
    HEADER_CODE,
    HEADER_NAME,
    HEADER_SALE_PRICE,
)
from gheymatyar.parsers.pioneers_html_xls import (
    convert_pioneers_html_xls_to_xlsx,
    read_pioneers_html_xls_rows,
)
from gheymatyar.services.pioneers_excel_writer import update_final_sale_prices
from gheymatyar.services.pioneers_legacy_xls_writer import (
    OLE2_SIGNATURE,
    LegacyXlsWriteError,
    pioneers_cell_value,
    render_pioneers_xls,
    write_pioneers_legacy_xls,
)
from gheymatyar.services.processing import ProcessingService
from gheymatyar.services.session_store import SessionStore

from .conftest import FIXTURES, REPO_ROOT

AZIN_XLS = FIXTURES / "pioneers" / "pioneers_azin_subset.xls"
AZIN_XLSX = FIXTURES / "pioneers" / "pioneers_azin_subset.xlsx"
SAMPLE_XLS = FIXTURES / "pioneers" / "pioneers_html_sample.xls"
# Real Pioneers header text (with its spacing) and the six sample products.
REAL_MARKUP_XLS = FIXTURES / "pioneers" / "pioneers_real_markup.xls"
CHECKER = REPO_ROOT / "scripts" / "windows" / "check_legacy_xls.py"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _sale_column(header: list[str]) -> int:
    return [value.strip() for value in header].index(HEADER_SALE_PRICE)


def _updates(rows: list[list[str]], picks: list[int], prices: list[str]) -> list[dict]:
    header = [value.strip() for value in rows[0]]
    code, name = header.index(HEADER_CODE), header.index(HEADER_NAME)
    return [
        {
            "row_number": pick,
            "pioneers_name": rows[pick - 1][name],
            "pioneers_code": rows[pick - 1][code],
            "final_sale_price": price,
        }
        for pick, price in zip(picks, prices)
    ]


def _typed(cell: xlrd.sheet.Cell) -> object:
    if cell.ctype in (xlrd.XL_CELL_EMPTY, xlrd.XL_CELL_BLANK):
        return ""
    if cell.ctype == xlrd.XL_CELL_BOOLEAN:
        return bool(cell.value)
    return cell.value


def _read_xls(path: Path) -> list[list[xlrd.sheet.Cell]]:
    data = path.read_bytes()
    assert data.startswith(OLE2_SIGNATURE)
    book = xlrd.open_workbook(file_contents=data)
    assert book.biff_version == 80
    assert book.nsheets == 1
    sheet = book.sheet_by_index(0)
    return [sheet.row(index) for index in range(sheet.nrows)]


def _assert_matches_source(
    source_rows: list[list[str]], exported: Path, picks: list[int], prices: list[str]
) -> None:
    """Exact text headers; every typed cell equals the source except the sale price."""
    out = _read_xls(exported)
    assert [cell.ctype for cell in out[0]] == [xlrd.XL_CELL_TEXT] * len(source_rows[0])
    assert [cell.value for cell in out[0]] == source_rows[0]
    assert len(out) - 1 == len(picks)
    sale = _sale_column(source_rows[0])
    for cells, pick, price in zip(out[1:], picks, prices):
        source = source_rows[pick - 1]
        assert len(cells) == len(source)
        for column, (cell, text) in enumerate(zip(cells, source)):
            if column == sale:
                assert cell.ctype == xlrd.XL_CELL_NUMBER
                assert cell.value == float(price)
                assert text != price
            else:
                assert _typed(cell) == pioneers_cell_value(text), (pick, column, text)


@pytest.mark.parametrize(
    ("original", "picks"),
    [
        # Rows 2 and 3 hold raw """1*32" quotes; 151 is the last row.
        (AZIN_XLS, [2, 3, 20, 40, 64, 80, 100, 125, 151]),
        # Row 7 holds نیوپایپ"بست کلکتور 1"" کد 15113.
        (SAMPLE_XLS, [3, 7]),
        (REAL_MARKUP_XLS, [2, 5, 7]),
    ],
)
def test_xls_source_exports_a_biff8_workbook_with_only_approved_rows(
    tmp_path: Path, original: Path, picks: list[int]
) -> None:
    before = _sha256(original)
    rows = read_pioneers_html_xls_rows(original)
    prices = [str(5_000_000 + index) for index in range(len(picks))]
    converted = convert_pioneers_html_xls_to_xlsx(original, tmp_path / "work.xlsx")
    update_final_sale_prices(converted, tmp_path / "a.xlsx", _updates(rows, picks, prices))

    result = write_pioneers_legacy_xls(tmp_path / "a.xlsx", tmp_path / "approved.xls")

    assert result.exported_row_count == len(picks)
    assert result.content_sha256 == _sha256(tmp_path / "approved.xls")
    _assert_matches_source(rows, tmp_path / "approved.xls", picks, prices)
    assert _sha256(original) == before


def test_real_header_spacing_and_all_40_columns_are_kept(tmp_path: Path) -> None:
    rows = read_pioneers_html_xls_rows(REAL_MARKUP_XLS)
    converted = convert_pioneers_html_xls_to_xlsx(REAL_MARKUP_XLS, tmp_path / "w.xlsx")
    update_final_sale_prices(converted, tmp_path / "a.xlsx", _updates(rows, [2], ["1234567"]))

    write_pioneers_legacy_xls(tmp_path / "a.xlsx", tmp_path / "out.xls")

    header = [cell.value for cell in _read_xls(tmp_path / "out.xls")[0]]
    assert len(header) == 40
    assert header[36] == HEADER_SALE_PRICE  # column AK
    assert header[22] == " کد تامین کننده :"
    assert header[18] == "سایر مشخصات 2 : "
    book = xlrd.open_workbook(str(tmp_path / "out.xls"))
    assert book.sheet_names() == ["لیست کالا"]
    assert book.codepage == 1200  # UTF-16 text


def test_xlsx_source_gives_the_same_workbook_as_the_xls_source(tmp_path: Path) -> None:
    """The .xlsx and .xls Azin fixtures hold the same cells."""
    picks = [2, 3, 50, 151]
    prices = ["1111111", "2222222", "3333333", "4444444"]
    rows = read_pioneers_html_xls_rows(AZIN_XLS)
    update_final_sale_prices(AZIN_XLSX, tmp_path / "x.xlsx", _updates(rows, picks, prices))
    converted = convert_pioneers_html_xls_to_xlsx(AZIN_XLS, tmp_path / "h.xlsx")
    update_final_sale_prices(converted, tmp_path / "y.xlsx", _updates(rows, picks, prices))

    write_pioneers_legacy_xls(tmp_path / "x.xlsx", tmp_path / "from-xlsx.xls")
    write_pioneers_legacy_xls(tmp_path / "y.xlsx", tmp_path / "from-xls.xls")

    _assert_matches_source(rows, tmp_path / "from-xlsx.xls", picks, prices)
    assert (tmp_path / "from-xlsx.xls").read_bytes() == (
        tmp_path / "from-xls.xls"
    ).read_bytes()


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("", ""),
        ("10018", 10018.0),
        ("0", 0.0),
        ("4610000", 4610000.0),
        ("1.5", 1.5),
        ("-3", -3.0),
        ("True", True),
        ("False", False),
        # Excel would drop the zeros, the trailing zero, or digits past 15.
        ("015113", "015113"),
        ("1.50", "1.50"),
        ("1234567890123456", "1234567890123456"),
        ("219 عدد", "219 عدد"),
        (" 12", " 12"),
        ("true", "true"),
        ('اذین شابلون """1/2"', 'اذین شابلون """1/2"'),
    ],
)
def test_cell_types_follow_excel_where_nothing_is_lost(
    text: str, expected: object
) -> None:
    value = pioneers_cell_value(text)
    assert value == expected
    assert type(value) is type(expected)


def test_header_cells_are_always_text() -> None:
    assert pioneers_cell_value("10018", header=True) == "10018"
    assert pioneers_cell_value("True", header=True) == "True"


def _workbook(tmp_path: Path, rows: list[list[object]]) -> Path:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "لیست کالا"
    for row in rows:
        sheet.append(row)
    path = tmp_path / "approved.xlsx"
    workbook.save(path)
    return path


HEADER = ["ردیف", "فعال", HEADER_CODE, "بارکد", HEADER_NAME, "مانده", HEADER_SALE_PRICE]


def test_typed_xlsx_cells_and_persian_text_round_trip(tmp_path: Path) -> None:
    source = _workbook(
        tmp_path,
        [HEADER, [7, True, "100", "015113", 'لوله <A> & "B"', 12.0, "4610000"]],
    )

    write_pioneers_legacy_xls(source, tmp_path / "out.xls")

    product = [_typed(cell) for cell in _read_xls(tmp_path / "out.xls")[1]]
    assert product == [7.0, True, 100.0, "015113", 'لوله <A> & "B"', 12.0, 4610000.0]


@pytest.mark.parametrize("bad_cell", ["=SUM(1,2)", "date"])
def test_values_pioneers_cannot_hold_are_rejected(
    tmp_path: Path, bad_cell: str
) -> None:
    from datetime import date

    value = date(2026, 10, 25) if bad_cell == "date" else bad_cell
    source = _workbook(
        tmp_path, [HEADER, [1, True, "100", "", "لوله", value, "1000"]]
    )

    with pytest.raises(LegacyXlsWriteError):
        write_pioneers_legacy_xls(source, tmp_path / "out.xls")
    assert not (tmp_path / "out.xls").exists()
    assert not list(tmp_path.glob(".legacy-*"))


def test_value_outside_the_header_columns_is_rejected(tmp_path: Path) -> None:
    source = _workbook(
        tmp_path, [HEADER, [1, True, "100", "", "لوله", "0", "1000", "extra"]]
    )
    with pytest.raises(LegacyXlsWriteError, match="outside the Pioneers header"):
        write_pioneers_legacy_xls(source, tmp_path / "out.xls")


def test_biff8_row_limit_is_enforced() -> None:
    rows = [["h"]] + [["x"]] * 65_536
    with pytest.raises(LegacyXlsWriteError, match="Too many rows"):
        render_pioneers_xls(rows)


def _large_html_catalog(path: Path, rows: int) -> None:
    """Grow the real Azin .xls to ``rows`` products with unique codes and names."""
    lines = AZIN_XLS.read_bytes().decode("utf-8-sig").split("\n")
    header_end = lines.index("</tr>") + 1
    body = lines[header_end:-4]
    blocks = [body[i : i + 42] for i in range(0, len(body), 42)]
    columns = [v.strip() for v in read_pioneers_html_xls_rows(AZIN_XLS)[0]]
    code, name = 1 + columns.index(HEADER_CODE), 1 + columns.index(HEADER_NAME)
    out = lines[:header_end]
    for index in range(rows):
        block = list(blocks[index % len(blocks)])
        block[code] = block[code][: block[code].index(">") + 1] + f"{900000 + index}</td>"
        block[name] = block[name].replace("</td>", f" نسخه {index}</td>")
        out.extend(block)
    out.extend(lines[-4:])
    path.write_bytes(("﻿" + "\n".join(out)).encode("utf-8"))


def _approved(product, index: int) -> UpdateCandidate:
    return UpdateCandidate(
        candidate_id=f"keep-{index}",
        row_number=product.row_number,
        pioneers_code=product.code,
        pioneers_name=product.name,
        supplier_code=f"S{index}",
        supplier_name=product.name,
        old_price=product.sale_price,
        new_price=Decimal(7_000_000 + index),
        absolute_change=Decimal("1"),
        percentage_change=Decimal("1"),
        match_type=None,
        status=MatchStatus.MATCHED,
        review_decision=ReviewDecision.APPROVE,
        warnings=[],
        suggestions=[],
        source_currency="rial",
        price_basis="printed",
    )


def test_nine_approved_of_6700_give_exactly_nine_xls_rows(tmp_path: Path) -> None:
    catalog = tmp_path / "گزارش لیست کالا.xls"
    _large_html_catalog(catalog, 6700)
    before = _sha256(catalog)
    picks = [2, 10, 50, 100, 500, 1000, 2500, 4000, 6701]
    service = ProcessingService(SessionStore())
    session = service.create_session()
    with catalog.open("rb") as handle:
        service.upload_pioneers_excel(session.session_id, catalog.name, handle)
    session = service.get_session(session.session_id)
    assert len(session.products) == 6700
    session.supplier_key = "azin_pipe"
    session.supplier_confirmed = True
    by_row = {product.row_number: product for product in session.products}
    session.candidates = [_approved(by_row[pick], i) for i, pick in enumerate(picks)]

    result, exported = service.export_for_download(session.session_id)

    assert result.exported_row_count == 9
    assert (exported.format, exported.exported_row_count) == ("xls", 9)
    assert exported.filename == "گزارش لیست کالا_updated.xls"
    legacy = session.legacy_output_path
    assert legacy is not None and legacy.suffix == ".xls"
    assert exported.content_sha256 == _sha256(legacy)
    _assert_matches_source(
        read_pioneers_html_xls_rows(catalog),
        legacy,
        picks,
        [str(7_000_000 + i) for i in range(9)],
    )
    assert _sha256(catalog) == before


def test_failed_xls_render_leaves_no_export(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = ProcessingService(SessionStore())
    session = service.create_session()
    with AZIN_XLS.open("rb") as handle:
        service.upload_pioneers_excel(session.session_id, AZIN_XLS.name, handle)
    session = service.get_session(session.session_id)
    session.supplier_key = "azin_pipe"
    session.supplier_confirmed = True
    session.candidates = [_approved(session.products[0], 0)]

    def fail(_source, _output):
        raise LegacyXlsWriteError("render failed")

    monkeypatch.setattr(processing, "write_pioneers_legacy_xls", fail)
    with pytest.raises(LegacyXlsWriteError):
        service.export_excel(session.session_id)

    assert session.output_path is None
    assert session.legacy_output_path is None
    assert not list(session.work_dir.glob("pioneers_updated.*"))


def test_crlf_copy_of_a_pioneers_xls_source_still_exports(tmp_path: Path) -> None:
    """A Windows checkout or editor may turn the source's LF into CRLF."""
    crlf = tmp_path / "crlf.xls"
    crlf.write_bytes(REAL_MARKUP_XLS.read_bytes().replace(b"\n", b"\r\n"))
    rows = read_pioneers_html_xls_rows(crlf)
    assert rows == read_pioneers_html_xls_rows(REAL_MARKUP_XLS)
    converted = convert_pioneers_html_xls_to_xlsx(crlf, tmp_path / "w.xlsx")
    update_final_sale_prices(converted, tmp_path / "a.xlsx", _updates(rows, [3, 7], ["111", "222"]))

    write_pioneers_legacy_xls(tmp_path / "a.xlsx", tmp_path / "out.xls")

    _assert_matches_source(rows, tmp_path / "out.xls", [3, 7], ["111", "222"])


def _run_checker(exported: Path, source: Path, code: str, price: str, rows: int):
    return subprocess.run(
        [
            sys.executable, str(CHECKER),
            "--exported", str(exported), "--source", str(source),
            "--code", code, "--price", price, "--rows", str(rows),
        ],
        capture_output=True,
        text=True,
    )


def test_checker_accepts_biff8_and_rejects_html_xlsx_and_altered_values(
    tmp_path: Path,
) -> None:
    rows = read_pioneers_html_xls_rows(REAL_MARKUP_XLS)
    converted = convert_pioneers_html_xls_to_xlsx(REAL_MARKUP_XLS, tmp_path / "w.xlsx")
    update_final_sale_prices(converted, tmp_path / "a.xlsx", _updates(rows, [3, 7], ["111", "222"]))
    write_pioneers_legacy_xls(tmp_path / "a.xlsx", tmp_path / "good.xls")
    code = rows[2][3]

    ok = _run_checker(tmp_path / "good.xls", REAL_MARKUP_XLS, code, "111", 2)
    assert ok.returncode == 0, ok.stdout + ok.stderr

    # The previous HTML-based export and a renamed .xlsx must both fail.
    (tmp_path / "html.xls").write_bytes(REAL_MARKUP_XLS.read_bytes())
    (tmp_path / "renamed.xls").write_bytes((tmp_path / "a.xlsx").read_bytes())
    # Same rows and prices as good.xls, with one non-price cell changed.
    sale = _sale_column(rows[0])
    first, second = list(rows[2]), list(rows[6])
    first[sale], second[sale] = "111", "222"
    assert render_pioneers_xls([rows[0], first, second]) == (
        tmp_path / "good.xls"
    ).read_bytes()
    second[31] = second[31] + " "
    (tmp_path / "value.xls").write_bytes(render_pioneers_xls([rows[0], first, second]))
    for name in ("html", "renamed", "value"):
        result = _run_checker(tmp_path / f"{name}.xls", REAL_MARKUP_XLS, code, "111", 2)
        assert result.returncode != 0, name
    assert "changed" in result.stdout + result.stderr


def test_default_download_is_never_html_or_xlsx(client, tmp_path: Path) -> None:
    """Regression: the default .xls is BIFF8, not HTML and not a renamed .xlsx."""
    session_id = client.post("/api/sessions").json()["session_id"]
    with AZIN_XLS.open("rb") as handle:
        uploaded = client.post(
            f"/api/sessions/{session_id}/pioneers-excel",
            files={"file": (AZIN_XLS.name, handle, "application/vnd.ms-excel")},
        )
    assert uploaded.status_code == 200, uploaded.text
    service = client.app.state.processing
    session = service.get_session(session_id)
    session.supplier_key = "azin_pipe"
    session.supplier_confirmed = True
    session.candidates = [_approved(session.products[0], 0)]

    exported = client.post(f"/api/sessions/{session_id}/export")
    assert exported.status_code == 200, exported.text
    assert exported.json()["output_filename"].endswith("_updated.xls")
    download = client.get(f"/api/sessions/{session_id}/download")

    assert download.status_code == 200, download.text
    assert download.headers["content-type"] == "application/vnd.ms-excel"
    assert download.content.startswith(OLE2_SIGNATURE)
    assert not download.content.startswith(b"PK")
    assert b"<Html>" not in download.content[:4096]
    assert b"\xef\xbb\xbf<" not in download.content[:8]
    xlsx = client.get(f"/api/sessions/{session_id}/download?format=xlsx")
    assert xlsx.content.startswith(b"PK")
