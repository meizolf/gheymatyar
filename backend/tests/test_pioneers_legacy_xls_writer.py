"""Approved exports in Pioneers' own HTML-based ``.xls`` format."""

from __future__ import annotations

import hashlib
from decimal import Decimal
from pathlib import Path

import pytest
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
    EVEN_ROW_CELL_OPEN,
    HEADER_CELL_OPEN,
    ODD_ROW_CELL_OPEN,
    LegacyXlsWriteError,
    data_cell_open,
    write_pioneers_legacy_xls,
)
from gheymatyar.services.processing import ProcessingService
from gheymatyar.services.session_store import SessionStore

from .conftest import FIXTURES

AZIN_XLS = FIXTURES / "pioneers" / "pioneers_azin_subset.xls"
AZIN_XLSX = FIXTURES / "pioneers" / "pioneers_azin_subset.xlsx"
SAMPLE_XLS = FIXTURES / "pioneers" / "pioneers_html_sample.xls"
# Real Pioneers markup: the header block and tags of a full export, holding
# the products of pioneers_html_sample.xls, striped by row position.
REAL_MARKUP_XLS = FIXTURES / "pioneers" / "pioneers_real_markup.xls"
DOCUMENT_START = ["<Html>", "<Body>", "<Table>"]
DOCUMENT_END = ["</Table>", "</Body>", "</Html>", ""]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _lines(path: Path) -> list[str]:
    raw = path.read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf")
    assert b"\r" not in raw
    return raw.decode("utf-8-sig").split("\n")


def _row_blocks(lines: list[str]) -> list[list[str]]:
    """``<tr>`` … ``</tr>`` line blocks; block 0 is the header row."""
    assert lines[:3] == DOCUMENT_START
    assert lines[-4:] == DOCUMENT_END
    blocks: list[list[str]] = []
    current: list[str] = []
    for line in lines[3:-4]:
        current.append(line)
        if line == "</tr>":
            assert current[0] == "<tr>"
            blocks.append(current)
            current = []
    assert not current
    return blocks


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


def _cell_body(line: str) -> str:
    """A ``<td …>text</td>`` line without its opening tag."""
    assert line.startswith("<td ") and line.endswith("</td>"), line[:60]
    return line[line.index(">") + 1 :]


def _assert_matches_original(
    original: Path, exported: Path, picks: list[int], prices: list[str]
) -> None:
    """Pioneers tags by position; cell text equals the source except the sale price."""
    source_blocks = _row_blocks(_lines(original))
    out_blocks = _row_blocks(_lines(exported))
    assert all(line.startswith(HEADER_CELL_OPEN) for line in out_blocks[0][1:-1])
    assert [_cell_body(line) for line in out_blocks[0][1:-1]] == [
        _cell_body(line) for line in source_blocks[0][1:-1]
    ]
    assert len(out_blocks) - 1 == len(picks)
    sale_line = 1 + _sale_column(read_pioneers_html_xls_rows(original)[0])
    for position, (out_block, pick, price) in enumerate(
        zip(out_blocks[1:], picks, prices), start=1
    ):
        source_block = source_blocks[pick - 1]
        assert len(out_block) == len(source_block)
        assert (out_block[0], out_block[-1]) == ("<tr>", "</tr>")
        tag = data_cell_open(position)
        for index in range(1, len(out_block) - 1):
            got, want = out_block[index], source_block[index]
            assert got.startswith(tag), (pick, index)
            if index == sale_line:
                assert _cell_body(got) == f"{price}</td>"
                assert _cell_body(got) != _cell_body(want)
            else:
                assert _cell_body(got) == _cell_body(want), (pick, index)


@pytest.mark.parametrize(
    ("original", "picks"),
    [
        # Rows 2 and 3 hold raw """1*32" quotes; 151 is the last row.
        (AZIN_XLS, [2, 3, 20, 40, 64, 80, 100, 125, 151]),
        # Row 7 holds نیوپایپ"بست کلکتور 1"" کد 15113.
        (SAMPLE_XLS, [3, 7]),
        (REAL_MARKUP_XLS, [4, 7]),
    ],
)
def test_xls_source_export_is_byte_identical_except_sale_price(
    tmp_path: Path, original: Path, picks: list[int]
) -> None:
    before = _sha256(original)
    rows = read_pioneers_html_xls_rows(original)
    prices = [str(5_000_000 + index) for index in range(len(picks))]
    converted = convert_pioneers_html_xls_to_xlsx(original, tmp_path / "work.xlsx")
    approved = tmp_path / "approved.xlsx"
    update_final_sale_prices(converted, approved, _updates(rows, picks, prices))

    result = write_pioneers_legacy_xls(approved, tmp_path / "approved.xls")

    assert result.exported_row_count == len(picks)
    assert result.content_sha256 == _sha256(tmp_path / "approved.xls")
    _assert_matches_original(original, tmp_path / "approved.xls", picks, prices)
    assert _sha256(original) == before


def test_leading_rows_of_a_real_pioneers_export_round_trip_byte_for_byte(
    tmp_path: Path,
) -> None:
    """The first products keep their positions, so only sale cells may differ."""
    rows = read_pioneers_html_xls_rows(REAL_MARKUP_XLS)
    # Product 14867 (row 6) has an empty name in Pioneers and cannot be approved.
    picks = [2, 3, 4, 5]
    prices = [str(9_000_000 + index) for index in range(len(picks))]
    converted = convert_pioneers_html_xls_to_xlsx(REAL_MARKUP_XLS, tmp_path / "w.xlsx")
    update_final_sale_prices(converted, tmp_path / "a.xlsx", _updates(rows, picks, prices))

    write_pioneers_legacy_xls(tmp_path / "a.xlsx", tmp_path / "out.xls")

    blocks = _row_blocks(_lines(REAL_MARKUP_XLS))
    sale_line = 1 + _sale_column(rows[0])
    expected = [*DOCUMENT_START, *blocks[0]]
    for block, price in zip(blocks[1 : 1 + len(picks)], prices):
        block = list(block)
        block[sale_line] = block[sale_line][: block[sale_line].index(">") + 1] + f"{price}</td>"
        expected.extend(block)
    expected.extend(DOCUMENT_END)
    assert (tmp_path / "out.xls").read_bytes() == (
        "\ufeff" + "\n".join(expected)
    ).encode("utf-8")
    # Header cells keep Pioneers' own spacing, e.g. ' کد تامین کننده :'.
    assert " کد تامین کننده :" in rows[0]


def test_writer_tags_are_the_real_pioneers_tags() -> None:
    blocks = _row_blocks(_lines(REAL_MARKUP_XLS))
    assert blocks[0][1].startswith(HEADER_CELL_OPEN)
    assert "10px;  font-weight: bold" in HEADER_CELL_OPEN
    assert blocks[1][1].startswith(ODD_ROW_CELL_OPEN)
    assert blocks[2][1].startswith(EVEN_ROW_CELL_OPEN)
    assert "#F5F5F5" in ODD_ROW_CELL_OPEN and "#FFFFFF" in EVEN_ROW_CELL_OPEN


def test_xlsx_source_renders_the_pioneers_xls_layout(tmp_path: Path) -> None:
    """The .xlsx and .xls Azin fixtures hold the same cells and give one file."""
    picks = [2, 3, 50, 151]
    prices = ["1111111", "2222222", "3333333", "4444444"]
    rows = read_pioneers_html_xls_rows(AZIN_XLS)
    update_final_sale_prices(AZIN_XLSX, tmp_path / "a.xlsx", _updates(rows, picks, prices))

    write_pioneers_legacy_xls(tmp_path / "a.xlsx", tmp_path / "from-xlsx.xls")

    _assert_matches_original(AZIN_XLS, tmp_path / "from-xlsx.xls", picks, prices)


def _workbook(tmp_path: Path, rows: list[list[object]]) -> Path:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "لیست کالا"
    for row in rows:
        sheet.append(row)
    path = tmp_path / "approved.xlsx"
    workbook.save(path)
    return path


HEADER = ["ردیف", "فعال", HEADER_CODE, HEADER_NAME, "مانده", HEADER_SALE_PRICE]


def test_cells_are_written_as_pioneers_text_and_markup_is_escaped(
    tmp_path: Path,
) -> None:
    source = _workbook(
        tmp_path,
        [HEADER, [7, True, "100", 'لوله <A> & "B"', 12.0, "4610000"]],
    )

    write_pioneers_legacy_xls(source, tmp_path / "out.xls")

    lines = _lines(tmp_path / "out.xls")
    header, product = _row_blocks(lines)
    assert all(line.startswith(HEADER_CELL_OPEN) for line in header[1:-1])
    assert product[1:-1] == [
        f"{ODD_ROW_CELL_OPEN}7</td>",
        f"{ODD_ROW_CELL_OPEN}True</td>",
        f"{ODD_ROW_CELL_OPEN}100</td>",
        f'{ODD_ROW_CELL_OPEN}لوله &lt;A&gt; &amp; "B"</td>',
        f"{ODD_ROW_CELL_OPEN}12</td>",
        f"{ODD_ROW_CELL_OPEN}4610000</td>",
    ]
    assert read_pioneers_html_xls_rows(tmp_path / "out.xls")[1] == [
        "7", "True", "100", 'لوله <A> & "B"', "12", "4610000",
    ]


@pytest.mark.parametrize(
    "bad_cell",
    ["=SUM(1,2)", pytest.param("date", id="date")],
)
def test_values_pioneers_cannot_hold_are_rejected(
    tmp_path: Path, bad_cell: str
) -> None:
    from datetime import date

    value = date(2026, 10, 25) if bad_cell == "date" else bad_cell
    source = _workbook(tmp_path, [HEADER, [1, True, "100", "لوله", value, "1000"]])

    with pytest.raises(LegacyXlsWriteError):
        write_pioneers_legacy_xls(source, tmp_path / "out.xls")
    assert not (tmp_path / "out.xls").exists()
    assert not list(tmp_path.glob(".legacy-*"))


def test_value_outside_the_header_columns_is_rejected(tmp_path: Path) -> None:
    source = _workbook(
        tmp_path, [HEADER, [1, True, "100", "لوله", "0", "1000", "extra"]]
    )
    with pytest.raises(LegacyXlsWriteError, match="outside the Pioneers header"):
        write_pioneers_legacy_xls(source, tmp_path / "out.xls")


def _large_html_catalog(path: Path, rows: int) -> list[list[str]]:
    """Grow the real Azin .xls to ``rows`` products with unique codes and names."""
    lines = _lines(AZIN_XLS)
    blocks = _row_blocks(lines)
    header_values = read_pioneers_html_xls_rows(AZIN_XLS)[0]
    code = 1 + [v.strip() for v in header_values].index(HEADER_CODE)
    name = 1 + [v.strip() for v in header_values].index(HEADER_NAME)
    out = [*DOCUMENT_START, *blocks[0]]
    for index in range(rows):
        block = list(blocks[1 + index % (len(blocks) - 1)])
        block[code] = block[code][: block[code].index(">") + 1] + f"{900000 + index}</td>"
        block[name] = block[name].replace("</td>", f" نسخه {index}</td>")
        out.extend(block)
    out.extend(DOCUMENT_END)
    path.write_bytes(("﻿" + "\n".join(out)).encode("utf-8"))
    return read_pioneers_html_xls_rows(path)


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
    assert exported.format == "xls"
    assert exported.filename == "گزارش لیست کالا_updated.xls"
    assert exported.exported_row_count == 9
    legacy = session.legacy_output_path
    assert legacy is not None and legacy.suffix == ".xls"
    assert exported.content_sha256 == _sha256(legacy)
    _assert_matches_original(
        catalog, legacy, picks, [str(7_000_000 + i) for i in range(9)]
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


def test_crlf_copy_of_a_pioneers_xls_still_exports_lf_pioneers_markup(
    tmp_path: Path,
) -> None:
    """A Windows checkout or editor may turn LF into CRLF; Pioneers writes LF."""
    crlf = tmp_path / "crlf.xls"
    crlf.write_bytes(REAL_MARKUP_XLS.read_bytes().replace(b"\n", b"\r\n"))
    rows = read_pioneers_html_xls_rows(crlf)
    assert rows == read_pioneers_html_xls_rows(REAL_MARKUP_XLS)
    converted = convert_pioneers_html_xls_to_xlsx(crlf, tmp_path / "w.xlsx")
    update_final_sale_prices(
        converted, tmp_path / "a.xlsx", _updates(rows, [3, 7], ["111", "222"])
    )

    write_pioneers_legacy_xls(tmp_path / "a.xlsx", tmp_path / "out.xls")

    _assert_matches_original(
        REAL_MARKUP_XLS, tmp_path / "out.xls", [3, 7], ["111", "222"]
    )


def _run_checker(exported: Path, source: Path, code: str, price: str, rows: int):
    import subprocess
    import sys

    from .conftest import REPO_ROOT

    return subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "windows" / "check_legacy_xls.py"),
            "--exported", str(exported), "--source", str(source),
            "--code", code, "--price", price, "--rows", str(rows),
        ],
        capture_output=True,
        text=True,
    )


def test_check_legacy_xls_script_rejects_altered_markup_and_values(
    tmp_path: Path,
) -> None:
    rows = read_pioneers_html_xls_rows(REAL_MARKUP_XLS)
    converted = convert_pioneers_html_xls_to_xlsx(REAL_MARKUP_XLS, tmp_path / "w.xlsx")
    update_final_sale_prices(
        converted, tmp_path / "a.xlsx", _updates(rows, [3, 7], ["111", "222"])
    )
    write_pioneers_legacy_xls(tmp_path / "a.xlsx", tmp_path / "good.xls")
    good = (tmp_path / "good.xls").read_bytes()
    code = rows[2][3]

    ok = _run_checker(tmp_path / "good.xls", REAL_MARKUP_XLS, code, "111", 2)
    assert ok.returncode == 0, ok.stdout + ok.stderr

    one_colour = good.replace(b"#FFFFFF", b"#F5F5F5")
    changed_value = good.replace("پارس پلاست".encode(), "پارس  پلاست".encode(), 1)
    for name, data in (("stripe", one_colour), ("value", changed_value), ("crlf", good.replace(b"\n", b"\r\n"))):
        bad = tmp_path / f"bad-{name}.xls"
        bad.write_bytes(data)
        assert data != good
        result = _run_checker(bad, REAL_MARKUP_XLS, code, "111", 2)
        assert result.returncode != 0, name
