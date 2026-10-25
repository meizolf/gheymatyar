#!/usr/bin/env python3
"""Check a GheymatYar Excel 97–2003 ``.xls`` export against its source file.

Reads the export with ``xlrd`` only and does not import the application, so
it checks the app's writer independently.

Asserts:
  * the export starts with the OLE2 signature, is not HTML or a zip/.xlsx,
    and ``xlrd`` reads it as a single-sheet BIFF8 (Excel 97–2003) workbook
  * the header row is text and equals the source header row, spacing and
    column order included (all 40 Pioneers columns)
  * the export holds exactly ``--rows`` product rows, all present in the source
  * the product with ``--code`` has a numeric ``نرخ فروش اصلی`` == ``--price``
  * every other cell of each exported row equals the source cell text, and
    text Excel would alter (e.g. leading-zero ``015113``) is still text
  * the source SHA-256 matches ``--source-sha256`` when given
"""

from __future__ import annotations

import argparse
import hashlib
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser
from pathlib import Path

import xlrd

SALE_HEADER = "نرخ فروش اصلی"
CODE_HEADER = "کد کالا"
OLE2 = bytes.fromhex("D0CF11E0A1B11AE1")


class _Cells(HTMLParser):
    """Cell text of a Pioneers HTML-based .xls source."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[list[str]] = []
        self._cell: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: object) -> None:
        if tag == "tr":
            self.rows.append([])
        elif tag == "td":
            self._cell = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "td" and self._cell is not None:
            self.rows[-1].append("".join(self._cell))
            self._cell = None

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell.append(data)


def _source_rows(source: Path) -> list[list[str]]:
    raw = source.read_bytes()
    if raw.startswith(b"\xef\xbb\xbf") or raw.lstrip()[:6].lower() == b"<html>":
        parser = _Cells()
        parser.feed(raw.decode("utf-8-sig"))
        parser.close()
        return parser.rows
    from openpyxl import load_workbook

    workbook = load_workbook(source, read_only=True, data_only=False)
    try:
        sheets = [
            ws
            for ws in workbook
            if SALE_HEADER in [c.value for c in next(ws.iter_rows(max_row=1), ())]
        ]
        if len(sheets) != 1:
            raise SystemExit("expected exactly one source product sheet")
        rows = [
            ["" if value is None else str(value) for value in row]
            for row in sheets[0].iter_rows(values_only=True)
        ]
    finally:
        workbook.close()
    width = max(i + 1 for i, value in enumerate(rows[0]) if value)
    return [row[:width] + [""] * (width - len(row[:width])) for row in rows]


def _cell_text(cell: xlrd.sheet.Cell) -> str:
    """The text a typed cell stands for, as a Pioneers export spells it."""
    if cell.ctype in (xlrd.XL_CELL_EMPTY, xlrd.XL_CELL_BLANK):
        return ""
    if cell.ctype == xlrd.XL_CELL_TEXT:
        return cell.value
    if cell.ctype == xlrd.XL_CELL_BOOLEAN:
        return "True" if cell.value else "False"
    if cell.ctype == xlrd.XL_CELL_NUMBER:
        value = float(cell.value)
        if value.is_integer():
            return str(int(value))
        return format(Decimal(repr(value)), "f")
    raise SystemExit(f"unexpected cell type {xlrd.sheet.ctype_text.get(cell.ctype)}")


def check(
    exported: Path,
    source: Path,
    *,
    code: str,
    price: str,
    rows: int,
    source_sha256: str | None,
) -> None:
    if source_sha256 is not None:
        if hashlib.sha256(source.read_bytes()).hexdigest() != source_sha256:
            raise SystemExit("source file changed during export")
    raw = exported.read_bytes()
    if raw.startswith(b"PK") or raw.lstrip(b"\xef\xbb\xbf \r\n\t")[:1] == b"<":
        raise SystemExit("export is a zip/.xlsx or HTML file, not an Excel 97–2003 .xls")
    if not raw.startswith(OLE2):
        raise SystemExit("export does not start with the OLE2 signature")
    try:
        book = xlrd.open_workbook(file_contents=raw)
    except xlrd.XLRDError as exc:
        raise SystemExit(f"xlrd cannot read the export: {exc}") from exc
    if book.biff_version != 80:
        raise SystemExit(f"export is BIFF {book.biff_version}, expected BIFF8 (80)")
    if book.nsheets != 1:
        raise SystemExit(f"expected one worksheet, found {book.nsheets}")
    sheet = book.sheet_by_index(0)

    src_rows = _source_rows(source)
    header = sheet.row(0)
    if any(cell.ctype not in (xlrd.XL_CELL_TEXT, xlrd.XL_CELL_EMPTY) for cell in header):
        raise SystemExit("export header cells must be text")
    out_header = [_cell_text(cell) for cell in header]
    if out_header != src_rows[0]:
        raise SystemExit("export header row differs from the source header row")
    headers = [value.strip() for value in out_header]
    sale = headers.index(SALE_HEADER)
    code_index = headers.index(CODE_HEADER)
    if sheet.nrows - 1 != rows:
        raise SystemExit(f"expected exactly {rows} product rows, got {sheet.nrows - 1}")

    by_code = {row[code_index].strip(): row for row in src_rows[1:]}
    found = None
    for row_index in range(1, sheet.nrows):
        cells = sheet.row(row_index)
        if len(cells) != len(src_rows[0]):
            raise SystemExit(f"product row {row_index} has {len(cells)} cells")
        texts = [_cell_text(cell) for cell in cells]
        src_row = by_code.get(texts[code_index].strip())
        if src_row is None:
            raise SystemExit(f"exported code {texts[code_index]!r} is not in the source")
        for column, (got, want) in enumerate(zip(texts, src_row)):
            if column == sale:
                continue
            if got != want:
                raise SystemExit(
                    f"code {texts[code_index]}: column {headers[column]!r} changed "
                    f"from {want!r} to {got!r}"
                )
        if cells[sale].ctype != xlrd.XL_CELL_NUMBER:
            raise SystemExit(f"code {texts[code_index]}: sale price is not a number")
        if texts[code_index].strip() == code.strip():
            if found is not None:
                raise SystemExit(f"approved code {code!r} appears more than once")
            found = texts[sale]
    if found is None:
        raise SystemExit(f"approved code {code!r} is not in the export")
    try:
        got = Decimal(found)
        want = Decimal(price.replace(",", "").strip())
    except InvalidOperation as exc:
        raise SystemExit("invalid sale price") from exc
    if got != want:
        raise SystemExit(f"sale price mismatch for code {code}: {found!r} != {price!r}")
    print(f"OK check_legacy_xls: BIFF8 .xls with {rows} row(s); code {code} == {want}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--exported", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--code", required=True)
    parser.add_argument("--price", required=True)
    parser.add_argument("--rows", type=int, default=1)
    parser.add_argument("--source-sha256")
    args = parser.parse_args(argv)
    check(
        args.exported,
        args.source,
        code=args.code,
        price=args.price,
        rows=args.rows,
        source_sha256=args.source_sha256,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
