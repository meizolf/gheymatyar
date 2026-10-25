"""Approved exports as a 3-column Excel 97–2003 (BIFF8) ``.xls``."""

from __future__ import annotations

import hashlib
import subprocess
import sys
from decimal import Decimal
from pathlib import Path

import pytest
import xlrd
import xlwt
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
    EXPORT_HEADERS,
    OLE2_SIGNATURE,
    ExportRow,
    LegacyXlsWriteError,
    render_pioneers_xls,
    write_pioneers_legacy_xls,
)
from gheymatyar.services.processing import ProcessingService
from gheymatyar.services.session_store import SessionStore

from .conftest import FIXTURES, REPO_ROOT

AZIN_XLS = FIXTURES / "pioneers" / "pioneers_azin_subset.xls"
AZIN_XLSX = FIXTURES / "pioneers" / "pioneers_azin_subset.xlsx"
SAMPLE_XLS = FIXTURES / "pioneers" / "pioneers_html_sample.xls"
REAL_MARKUP_XLS = FIXTURES / "pioneers" / "pioneers_real_markup.xls"
CHECKER = REPO_ROOT / "scripts" / "windows" / "check_legacy_xls.py"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _columns(header: list[str]) -> tuple[int, int, int]:
    stripped = [value.strip() for value in header]
    return (
        stripped.index(HEADER_CODE),
        stripped.index(HEADER_NAME),
        stripped.index(HEADER_SALE_PRICE),
    )


def _updates(rows: list[list[object]], picks: list[int], prices: list[str]) -> list[dict]:
    code, name, _sale = _columns([str(value) for value in rows[0]])
    return [
        {
            "row_number": pick,
            "pioneers_name": str(rows[pick - 1][name]),
            "pioneers_code": str(rows[pick - 1][code]),
            "final_sale_price": price,
        }
        for pick, price in zip(picks, prices)
    ]


def _read_xls(path: Path) -> list[list[xlrd.sheet.Cell]]:
    """Read with xlrd alone: BIFF8, one sheet, three columns."""
    data = path.read_bytes()
    assert data.startswith(OLE2_SIGNATURE)
    book = xlrd.open_workbook(file_contents=data)
    assert book.biff_version == 80
    assert book.nsheets == 1
    sheet = book.sheet_by_index(0)
    assert sheet.ncols == 3
    return [sheet.row(index) for index in range(sheet.nrows)]


def _products(path: Path) -> list[tuple[str, str, float]]:
    """(code, name, price) per product row, checking each cell type."""
    rows = _read_xls(path)
    assert [cell.value for cell in rows[0]] == ["کد کالا", "نام کالا", "نرخ فروش اصلی"]
    assert [cell.ctype for cell in rows[0]] == [xlrd.XL_CELL_TEXT] * 3
    products = []
    for code, name, price in rows[1:]:
        assert code.ctype == xlrd.XL_CELL_TEXT
        assert name.ctype == xlrd.XL_CELL_TEXT
        assert price.ctype == xlrd.XL_CELL_NUMBER
        products.append((code.value, name.value, price.value))
    return products


def _export_html(
    tmp_path: Path, original: Path, picks: list[int], prices: list[str]
) -> tuple[list[list[str]], Path]:
    rows = read_pioneers_html_xls_rows(original)
    converted = convert_pioneers_html_xls_to_xlsx(original, tmp_path / "work.xlsx")
    result = update_final_sale_prices(
        converted, tmp_path / "approved.xlsx", _updates(rows, picks, prices)
    )
    write_pioneers_legacy_xls(tmp_path / "approved.xlsx", tmp_path / "out.xls", result.changes)
    return rows, tmp_path / "out.xls"


def test_export_headers_are_exactly_the_three_pioneers_columns() -> None:
    assert EXPORT_HEADERS == ("کد کالا", "نام کالا", "نرخ فروش اصلی")


@pytest.mark.parametrize(
    ("original", "picks"),
    [
        # Rows 2 and 3 hold raw """1*32" quotes; 151 is the last row.
        (AZIN_XLS, [2, 3, 20, 40, 64, 80, 100, 125, 151]),
        (SAMPLE_XLS, [3, 7]),
        (REAL_MARKUP_XLS, [2, 5, 7]),
    ],
)
def test_xls_source_exports_code_name_and_rial_price_only(
    tmp_path: Path, original: Path, picks: list[int]
) -> None:
    before = _sha256(original)
    prices = [str(5_000_000 + index) for index in range(len(picks))]

    rows, out = _export_html(tmp_path, original, picks, prices)

    code, name, _sale = _columns(rows[0])
    assert _products(out) == [
        (rows[pick - 1][code], rows[pick - 1][name], float(price))
        for pick, price in zip(picks, prices)
    ]
    assert _sha256(original) == before


def test_rows_follow_the_sheet_order_whatever_the_update_order(tmp_path: Path) -> None:
    rows, out = _export_html(tmp_path, AZIN_XLS, [80, 2, 151], ["800", "200", "1510"])
    code, _name, _sale = _columns(rows[0])
    assert [product[0] for product in _products(out)] == [
        rows[1][code], rows[79][code], rows[150][code]
    ]
    assert [product[2] for product in _products(out)] == [200.0, 800.0, 1510.0]


def test_xlsx_source_gives_the_same_file_as_the_xls_source(tmp_path: Path) -> None:
    """The .xlsx and .xls Azin fixtures hold the same cells."""
    picks, prices = [2, 3, 50, 151], ["1111111", "2222222", "3333333", "4444444"]
    rows = read_pioneers_html_xls_rows(AZIN_XLS)
    from_xlsx = update_final_sale_prices(
        AZIN_XLSX, tmp_path / "x.xlsx", _updates(rows, picks, prices)
    )
    write_pioneers_legacy_xls(tmp_path / "x.xlsx", tmp_path / "from-xlsx.xls", from_xlsx.changes)
    _rows, from_xls = _export_html(tmp_path, AZIN_XLS, picks, prices)

    assert (tmp_path / "from-xlsx.xls").read_bytes() == from_xls.read_bytes()


def _workbook(tmp_path: Path, rows: list[list[object]]) -> Path:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "لیست کالا"
    for row in rows:
        sheet.append(row)
    path = tmp_path / "source.xlsx"
    workbook.save(path)
    return path


HEADER = ["ردیف", HEADER_CODE, "بارکد", HEADER_NAME, "مانده", HEADER_SALE_PRICE]


def test_leading_zero_codes_and_exact_names_are_kept(tmp_path: Path) -> None:
    source = _workbook(
        tmp_path,
        [
            HEADER,
            ["1", "00123", "015113", " پنج راه برنجی ...", "8 عدد", "1000"],
            ["2", "0456", "", "شلنگ 12 تراز ", "0", "2000"],
        ],
    )
    from gheymatyar.parsers.pioneers_excel_parser import PioneersExcelParser

    products = PioneersExcelParser().parse(source).products
    assert [p.code for p in products] == ["00123", "0456"]
    result = update_final_sale_prices(
        source,
        tmp_path / "approved.xlsx",
        [
            {"row_number": p.row_number, "pioneers_name": p.name,
             "pioneers_code": p.code, "final_sale_price": price}
            for p, price in zip(products, ["4610000", "32400000"])
        ],
    )

    write_pioneers_legacy_xls(tmp_path / "approved.xlsx", tmp_path / "out.xls", result.changes)

    assert _products(tmp_path / "out.xls") == [
        ("00123", " پنج راه برنجی ...", 4610000.0),
        ("0456", "شلنگ 12 تراز ", 32400000.0),
    ]


def test_changes_that_disagree_with_the_workbook_are_rejected(tmp_path: Path) -> None:
    rows = read_pioneers_html_xls_rows(AZIN_XLS)
    converted = convert_pioneers_html_xls_to_xlsx(AZIN_XLS, tmp_path / "w.xlsx")
    result = update_final_sale_prices(
        converted, tmp_path / "a.xlsx", _updates(rows, [2, 3], ["100", "200"])
    )
    from dataclasses import replace

    wrong_price = [replace(result.changes[0], new_final_sale_price=Decimal("999")), result.changes[1]]
    wrong_code = [replace(result.changes[0], pioneers_code="99999"), result.changes[1]]
    for changes in (wrong_price, wrong_code, result.changes[:1]):
        with pytest.raises(LegacyXlsWriteError):
            write_pioneers_legacy_xls(tmp_path / "a.xlsx", tmp_path / "out.xls", changes)
        assert not (tmp_path / "out.xls").exists()
    assert not list(tmp_path.glob(".legacy-*"))


def test_biff8_row_limit_is_enforced() -> None:
    rows = [ExportRow(code="1", name="n", price=1)] * 65_536
    with pytest.raises(LegacyXlsWriteError, match="Too many rows"):
        render_pioneers_xls(rows)


def _large_html_catalog(path: Path, rows: int) -> None:
    """Grow the real Azin .xls to ``rows`` products with unique codes and names."""
    lines = AZIN_XLS.read_bytes().decode("utf-8-sig").split("\n")
    header_end = lines.index("</tr>") + 1
    body = lines[header_end:-4]
    blocks = [body[i : i + 42] for i in range(0, len(body), 42)]
    code, name, _sale = _columns(read_pioneers_html_xls_rows(AZIN_XLS)[0])
    out = lines[:header_end]
    for index in range(rows):
        block = list(blocks[index % len(blocks)])
        block[code + 1] = block[code + 1][: block[code + 1].index(">") + 1] + f"{900000 + index}</td>"
        block[name + 1] = block[name + 1].replace("</td>", f" نسخه {index}</td>")
        out.extend(block)
    out.extend(lines[-4:])
    path.write_bytes(("﻿" + "\n".join(out)).encode("utf-8"))


def _candidate(product, key: str, *, price: int, status=MatchStatus.MATCHED,
               decision=ReviewDecision.APPROVE) -> UpdateCandidate:
    return UpdateCandidate(
        candidate_id=key,
        row_number=product.row_number,
        pioneers_code=product.code,
        pioneers_name=product.name,
        supplier_code=f"S-{key}",
        supplier_name=product.name,
        old_price=product.sale_price,
        new_price=Decimal(price),
        absolute_change=Decimal("1"),
        percentage_change=Decimal("1"),
        match_type=None,
        status=status,
        review_decision=decision,
        warnings=[],
        suggestions=[],
        source_currency="rial",
        price_basis="printed",
    )


def test_nine_approved_of_6700_give_exactly_nine_rows(tmp_path: Path) -> None:
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
    session.candidates = [
        _candidate(by_row[pick], f"keep-{i}", price=7_000_000 + i)
        for i, pick in enumerate(picks)
    ]

    result, exported = service.export_for_download(session.session_id)

    assert result.exported_row_count == 9
    assert (exported.format, exported.exported_row_count) == ("xls", 9)
    assert exported.filename == "گزارش لیست کالا_updated.xls"
    legacy = session.legacy_output_path
    assert legacy is not None and exported.content_sha256 == _sha256(legacy)
    source = read_pioneers_html_xls_rows(catalog)
    code, name, _sale = _columns(source[0])
    assert _products(legacy) == [
        (source[pick - 1][code], source[pick - 1][name], float(7_000_000 + i))
        for i, pick in enumerate(picks)
    ]
    assert _sha256(catalog) == before


def test_failed_xls_render_leaves_no_export(monkeypatch: pytest.MonkeyPatch) -> None:
    service = ProcessingService(SessionStore())
    session = service.create_session()
    with AZIN_XLS.open("rb") as handle:
        service.upload_pioneers_excel(session.session_id, AZIN_XLS.name, handle)
    session = service.get_session(session.session_id)
    session.supplier_key = "azin_pipe"
    session.supplier_confirmed = True
    session.candidates = [_candidate(session.products[0], "keep", price=7_000_000)]

    def fail(*_args):
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
    rows, out = _export_html(tmp_path, crlf, [3, 7], ["111", "222"])
    code, name, _sale = _columns(rows[0])
    assert _products(out) == [
        (rows[2][code], rows[2][name], 111.0),
        (rows[6][code], rows[6][name], 222.0),
    ]


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


def _xls(path: Path, rows: list[list[object]]) -> Path:
    workbook = xlwt.Workbook(encoding="utf-8")
    sheet = workbook.add_sheet("لیست کالا")
    for r, row in enumerate(rows):
        for c, value in enumerate(row):
            sheet.write(r, c, value)
    workbook.save(str(path))
    return path


def test_checker_accepts_the_export_and_rejects_other_files(tmp_path: Path) -> None:
    rows, good = _export_html(tmp_path, REAL_MARKUP_XLS, [3, 7], ["111", "222"])
    code, name, _sale = _columns(rows[0])
    first, second = rows[2], rows[6]

    ok = _run_checker(good, REAL_MARKUP_XLS, first[code], "111", 2)
    assert ok.returncode == 0, ok.stdout + ok.stderr

    header = list(EXPORT_HEADERS)
    bad = {
        "html": REAL_MARKUP_XLS.read_bytes(),
        "renamed-xlsx": (tmp_path / "approved.xlsx").read_bytes(),
        "extra-column": _xls(tmp_path / "x1.xls", [header + ["بارکد"], [first[code], first[name], 111.0, ""], [second[code], second[name], 222.0, ""]]).read_bytes(),
        "numeric-code": _xls(tmp_path / "x2.xls", [header, [float(first[code]), first[name], 111.0], [second[code], second[name], 222.0]]).read_bytes(),
        "text-price": _xls(tmp_path / "x3.xls", [header, [first[code], first[name], "111"], [second[code], second[name], 222.0]]).read_bytes(),
        "changed-name": _xls(tmp_path / "x4.xls", [header, [first[code], first[name] + " ", 111.0], [second[code], second[name], 222.0]]).read_bytes(),
        "wrong-order": _xls(tmp_path / "x5.xls", [["نام کالا", "کد کالا", "نرخ فروش اصلی"], [first[name], first[code], 111.0], [second[name], second[code], 222.0]]).read_bytes(),
    }
    for label, data in bad.items():
        path = tmp_path / f"bad-{label}.xls"
        path.write_bytes(data)
        result = _run_checker(path, REAL_MARKUP_XLS, first[code], "111", 2)
        assert result.returncode != 0, label


def _upload(client, path: Path) -> str:
    session_id = client.post("/api/sessions").json()["session_id"]
    with path.open("rb") as handle:
        uploaded = client.post(
            f"/api/sessions/{session_id}/pioneers-excel",
            files={"file": (path.name, handle, "application/vnd.ms-excel")},
        )
    assert uploaded.status_code == 200, uploaded.text
    return session_id


def test_only_approved_changed_products_are_downloaded(client) -> None:
    """Excluded, ignored, unapproved, unchanged, and unmatched products are absent."""
    session_id = _upload(client, AZIN_XLS)
    session = client.app.state.processing.get_session(session_id)
    session.supplier_key = "azin_pipe"
    session.supplier_confirmed = True
    p = session.products
    session.candidates = [
        _candidate(p[0], "approved-a", price=1_111_111),
        _candidate(p[1], "excluded", price=2_222_222, decision=ReviewDecision.EXCLUDE),
        _candidate(p[2], "approved-b", price=3_333_333),
        _candidate(p[3], "include-unapproved", price=4_444_444, decision=ReviewDecision.INCLUDE),
        _candidate(p[4], "ignored", price=5_555_555, status=MatchStatus.IGNORED,
                   decision=ReviewDecision.EXCLUDE),
        _candidate(p[5], "unchanged", price=int(p[5].sale_price)),
        _candidate(p[6], "unmatched", price=6_666_666, status=MatchStatus.UNMATCHED,
                   decision=ReviewDecision.EXCLUDE),
    ]

    exported = client.post(f"/api/sessions/{session_id}/export")
    assert exported.status_code == 200, exported.text
    assert exported.json()["exported_row_count"] == 2
    download = client.get(f"/api/sessions/{session_id}/download")

    assert download.status_code == 200, download.text
    assert download.headers["content-type"] == "application/vnd.ms-excel"
    assert download.headers["x-exported-row-count"] == "2"
    path = Path(client.app.state.processing.get_session(session_id).work_dir) / "check.xls"
    path.write_bytes(download.content)
    assert [(code, price) for code, _name, price in _products(path)] == [
        (p[0].code, 1_111_111.0),
        (p[2].code, 3_333_333.0),
    ]


def test_default_download_is_never_html_or_xlsx(client) -> None:
    """Regression: the default .xls is BIFF8, not HTML and not a renamed .xlsx."""
    session_id = _upload(client, AZIN_XLS)
    session = client.app.state.processing.get_session(session_id)
    session.supplier_key = "azin_pipe"
    session.supplier_confirmed = True
    session.candidates = [_candidate(session.products[0], "keep", price=7_000_000)]

    exported = client.post(f"/api/sessions/{session_id}/export")
    assert exported.status_code == 200, exported.text
    assert exported.json()["output_filename"].endswith("_updated.xls")
    download = client.get(f"/api/sessions/{session_id}/download")

    assert download.status_code == 200, download.text
    assert download.content.startswith(OLE2_SIGNATURE)
    assert not download.content.startswith(b"PK")
    assert b"<Html>" not in download.content[:4096]
    xlsx = client.get(f"/api/sessions/{session_id}/download?format=xlsx")
    assert xlsx.content.startswith(b"PK")
