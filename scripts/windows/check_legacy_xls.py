#!/usr/bin/env python3
"""Check a GheymatYar Pioneers ``.xls`` export against its source file.

Does not import the application, so it checks the app's writer independently.

Asserts:
  * the export is a UTF-8 (BOM) HTML ``.xls`` with Pioneers' document layout
    (``<Html>``, ``<Body>``, ``<Table>``, one ``<td>`` per line, ``\\n`` line
    endings), Pioneers' header tag, and product rows striped by position
    (``#F5F5F5`` first, then ``#FFFFFF``), as in a full Pioneers export
  * the header row equals the source header row, in the same column order
  * the export holds exactly ``--rows`` product rows, all present in the source
  * the product with ``--code`` has ``نرخ فروش اصلی`` == ``--price``
  * every other cell of each exported row equals the source row
  * for an HTML ``.xls`` source, the text of every exported cell line is
    byte-identical to the source line except the ``نرخ فروش اصلی`` cell
  * the source SHA-256 matches ``--source-sha256`` when given
"""

from __future__ import annotations

import argparse
import hashlib
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser
from pathlib import Path

SALE_HEADER = "نرخ فروش اصلی"
CODE_HEADER = "کد کالا"
BOM = b"\xef\xbb\xbf"
# Tags of a full Pioneers export. The header has two spaces before font-weight.
HEADER_TD = (
    '<td colspan="1" dir="rtl" align="center" style="border-style: solid; '
    "border-width: 1px; font-family: 'B Yekan'; font-size: 10px;  "
    'font-weight: bold; background-color: #C0C0C0;">'
)
ROW_TDS = tuple(
    '<td colspan="1" dir="rtl" align="center" style="border-style: solid; '
    "border-width: 1px; font-family: 'B Yekan'; font-size: 10px; "
    f'background-color: {color};">'
    for color in ("#F5F5F5", "#FFFFFF")
)


def _expected_td(row_index: int) -> str:
    """Tag for block ``row_index`` (0 is the header)."""
    return HEADER_TD if row_index == 0 else ROW_TDS[(row_index - 1) % 2]


def _cell_body(line: str) -> str:
    return line[line.index(">") + 1 :]


class _Cells(HTMLParser):
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


def _html_rows(text: str) -> list[list[str]]:
    parser = _Cells()
    parser.feed(text)
    parser.close()
    return parser.rows


def _row_blocks(lines: list[str]) -> list[list[str]]:
    """Group document lines into ``<tr>`` … ``</tr>`` blocks."""
    blocks: list[list[str]] = []
    current: list[str] | None = None
    for line in lines:
        if line == "<tr>":
            current = [line]
        elif current is not None:
            current.append(line)
            if line == "</tr>":
                blocks.append(current)
                current = None
    return blocks


def _source_rows(source: Path) -> tuple[list[list[str]], list[list[str]] | None]:
    raw = source.read_bytes()
    if raw.startswith(BOM) or raw.lstrip()[:6].lower() == b"<html>":
        # A Windows checkout may hold CRLF; Pioneers itself writes LF.
        text = raw.decode("utf-8-sig").replace("\r\n", "\n")
        return _html_rows(text), _row_blocks(text.split("\n"))
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
    return [row[:width] + [""] * (width - len(row[:width])) for row in rows], None


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
    if not raw.startswith(BOM):
        raise SystemExit("export is not UTF-8 with BOM like a Pioneers .xls")
    if raw.startswith(BOM + b"PK") or b"\r" in raw:
        raise SystemExit("export is not a Pioneers HTML .xls (zip or CRLF found)")
    text = raw.decode("utf-8-sig")
    lines = text.split("\n")
    if lines[:3] != ["<Html>", "<Body>", "<Table>"] or lines[-4:] != [
        "</Table>",
        "</Body>",
        "</Html>",
        "",
    ]:
        raise SystemExit("export does not have the Pioneers <Html><Body><Table> layout")
    blocks = _row_blocks(lines)
    for index, block in enumerate(blocks):
        expected_open = _expected_td(index)
        for line in block[1:-1]:
            if not (line.startswith(expected_open) and line.endswith("</td>")):
                raise SystemExit(f"row {index + 1} has a non-Pioneers cell line: {line[:80]!r}")
    if 3 + sum(len(block) for block in blocks) + 4 != len(lines):
        raise SystemExit("export has content outside the Pioneers table rows")

    out_rows = _html_rows(text)
    src_rows, src_blocks = _source_rows(source)
    if out_rows[0] != src_rows[0]:
        raise SystemExit("export header row differs from the source header row")
    headers = [value.strip() for value in out_rows[0]]
    sale = headers.index(SALE_HEADER)
    code_index = headers.index(CODE_HEADER)
    products = out_rows[1:]
    if len(products) != rows:
        raise SystemExit(f"expected exactly {rows} product rows, got {len(products)}")
    by_code = {row[code_index].strip(): (i, row) for i, row in enumerate(src_rows[1:], 1)}
    for out_index, row in enumerate(products, start=1):
        if len(row) != len(src_rows[0]):
            raise SystemExit(f"product row {out_index} has {len(row)} cells")
        hit = by_code.get(row[code_index].strip())
        if hit is None:
            raise SystemExit(f"exported code {row[code_index]!r} is not in the source")
        src_index, src_row = hit
        for column, (got, want) in enumerate(zip(row, src_row)):
            if column != sale and got != want:
                raise SystemExit(
                    f"code {row[code_index]}: column {headers[column]!r} changed "
                    f"from {want!r} to {got!r}"
                )
        if src_blocks is not None:
            out_block, src_block = blocks[out_index], src_blocks[src_index]
            for line_index, (got, want) in enumerate(zip(out_block, src_block)):
                if line_index in (0, len(out_block) - 1):
                    if got != want:
                        raise SystemExit(f"code {row[code_index]}: row markup differs")
                    continue
                if line_index != sale + 1 and _cell_body(got) != _cell_body(want):
                    raise SystemExit(
                        f"code {row[code_index]}: source line {line_index} is not byte-identical"
                    )
    match = [row for row in products if row[code_index].strip() == code.strip()]
    if len(match) != 1:
        raise SystemExit(f"expected approved code {code!r} exactly once")
    try:
        got = Decimal(match[0][sale].strip())
        want = Decimal(price.replace(",", "").strip())
    except InvalidOperation as exc:
        raise SystemExit("invalid sale price") from exc
    if got != want or not match[0][sale].strip().isdigit():
        raise SystemExit(f"sale price mismatch for code {code}: {match[0][sale]!r} != {price!r}")
    print(f"OK check_legacy_xls: {rows} Pioneers .xls row(s); code {code} == {want}")


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
