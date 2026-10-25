"""Write the approved-only export in Pioneers' own HTML-based ``.xls`` format.

Pioneers ``گزارش لیست کالا.xls`` files are not OLE/BIFF workbooks. They are
UTF-8 (with BOM) HTML documents with one ``<Table>``: ``<Html>``, ``<Body>``,
``<Table>``, one ``<tr>`` per row, and one ``<td>`` per line. Header cells use
one fixed opening tag and product rows alternate between two, by position.
Lines end with ``\\n`` and the text is written as is: Pioneers does not escape
quotes. Cell text, header spacing included, comes from the uploaded file.

This writer does not pick rows or prices. It renders the workbook that
``update_final_sale_prices`` has already produced and verified, so the same
approved rows, product identities, and ``نرخ فروش اصلی`` text are used. Only
the product sheet is written, because the Pioneers format has one table.

The written file is read back with the same HTML reader used for uploads, and
must give exactly the rendered cells before it is published.
"""

from __future__ import annotations

import hashlib
import os
import tempfile
from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal
from pathlib import Path
from typing import Sequence

from openpyxl import load_workbook
from openpyxl.cell.cell import Cell
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

from gheymatyar.parsers.errors import PioneersExcelError
from gheymatyar.parsers.pioneers_excel_parser import (
    HEADER_CODE,
    HEADER_NAME,
    HEADER_ROW,
    HEADER_SALE_PRICE,
)
from gheymatyar.parsers.pioneers_html_xls import read_pioneers_html_xls_rows
from gheymatyar.parsers.workbook_format import WorkbookFormat, detect_workbook_format
from gheymatyar.services.errors import PioneersExcelWriteError

_BOM = "﻿"
_NEWLINE = "\n"
# Opening tags copied verbatim from a full Pioneers export (6,774 products).
# The header tag has two spaces before font-weight. Data rows alternate
# #F5F5F5 / #FFFFFF, starting with #F5F5F5 on the first product row.
HEADER_CELL_OPEN = (
    '<td colspan="1" dir="rtl" align="center" style="border-style: solid; '
    "border-width: 1px; font-family: 'B Yekan'; font-size: 10px;  "
    'font-weight: bold; background-color: #C0C0C0;">'
)
ODD_ROW_CELL_OPEN = (
    '<td colspan="1" dir="rtl" align="center" style="border-style: solid; '
    "border-width: 1px; font-family: 'B Yekan'; font-size: 10px; "
    'background-color: #F5F5F5;">'
)
EVEN_ROW_CELL_OPEN = (
    '<td colspan="1" dir="rtl" align="center" style="border-style: solid; '
    "border-width: 1px; font-family: 'B Yekan'; font-size: 10px; "
    'background-color: #FFFFFF;">'
)


def data_cell_open(product_index: int) -> str:
    """Opening tag for the 1-based ``product_index``-th product row."""
    return ODD_ROW_CELL_OPEN if product_index % 2 == 1 else EVEN_ROW_CELL_OPEN
_DOCUMENT_START = ("<Html>", "<Body>", "<Table>")
_DOCUMENT_END = ("</Table>", "</Body>", "</Html>")
_REQUIRED_HEADERS = (HEADER_CODE, HEADER_NAME, HEADER_SALE_PRICE)


class LegacyXlsWriteError(PioneersExcelWriteError, ValueError):
    """The approved export cannot be written as a Pioneers HTML ``.xls``."""


@dataclass(frozen=True)
class LegacyXlsResult:
    """A published Pioneers HTML ``.xls`` export."""

    output_path: str
    exported_row_count: int
    content_sha256: str


def write_pioneers_legacy_xls(
    approved_workbook: str | Path,
    output_path: str | Path,
) -> LegacyXlsResult:
    """Render a verified approved-only ``.xlsx`` as a Pioneers HTML ``.xls``.

    ``approved_workbook`` must be the output of ``update_final_sale_prices``.
    Every cell on the product sheet is written as text in its original column
    order. Formulas, dates, and values outside the header columns are rejected
    rather than guessed, because a Pioneers export never contains them.
    """
    source = Path(approved_workbook)
    output = Path(output_path)
    rows = _product_rows_as_text(source)
    payload = render_pioneers_html_xls(rows)
    _publish(payload, output, expected=rows)
    return LegacyXlsResult(
        output_path=str(output.resolve()),
        exported_row_count=len(rows) - 1,
        content_sha256=hashlib.sha256(payload).hexdigest(),
    )


def render_pioneers_html_xls(rows: Sequence[Sequence[str]]) -> bytes:
    """Serialize a header row plus product rows exactly as Pioneers does."""
    if not rows:
        raise LegacyXlsWriteError(
            "Cannot write a Pioneers .xls without a header row"
        )
    lines = [*_DOCUMENT_START]
    for index, row in enumerate(rows):
        cell_open = HEADER_CELL_OPEN if index == 0 else data_cell_open(index)
        lines.append("<tr>")
        lines.extend(f"{cell_open}{_escape(value)}</td>" for value in row)
        lines.append("</tr>")
    lines.extend(_DOCUMENT_END)
    return (_BOM + _NEWLINE.join(lines) + _NEWLINE).encode("utf-8")


def _escape(value: str) -> str:
    """Escape only what would change the HTML structure.

    Pioneers writes quotes as is (``اذین شابلون \"\"\"1/2\"``). ``&``, ``<``,
    and ``>`` have not been seen in its exports, but must not open a tag.
    """
    return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _product_rows_as_text(source: Path) -> list[list[str]]:
    try:
        workbook = load_workbook(source, read_only=False, data_only=False)
    except Exception as exc:  # noqa: BLE001 - wrap openpyxl failures
        raise LegacyXlsWriteError(
            "Failed to open the approved export workbook",
            filename=source,
            reason=str(exc),
        ) from exc
    try:
        worksheet = _product_sheet(workbook.worksheets, source)
        width = _header_width(worksheet)
        rows: list[list[str]] = []
        for row_number in range(HEADER_ROW, (worksheet.max_row or HEADER_ROW) + 1):
            cells = [worksheet.cell(row_number, column) for column in range(1, width + 1)]
            _reject_values_outside_header(worksheet, row_number, width, source)
            values = [_cell_text(cell, source, worksheet.title) for cell in cells]
            if row_number > HEADER_ROW and not any(values):
                raise LegacyXlsWriteError(
                    "Approved export contains an empty product row",
                    filename=source,
                    sheet=worksheet.title,
                    row=row_number,
                )
            rows.append(values)
    finally:
        workbook.close()
    if len(rows) < 2:
        raise LegacyXlsWriteError(
            "Approved export has no product rows",
            filename=source,
        )
    return rows


def _product_sheet(worksheets: Sequence[Worksheet], source: Path) -> Worksheet:
    """The only sheet whose row 1 names each Pioneers product header once."""
    matches = []
    for worksheet in worksheets:
        headers = [
            cell.value.strip()
            for cell in worksheet[HEADER_ROW]
            if isinstance(cell.value, str)
        ]
        if all(headers.count(header) == 1 for header in _REQUIRED_HEADERS):
            matches.append(worksheet)
    if len(matches) != 1:
        raise LegacyXlsWriteError(
            "Approved export must have exactly one Pioneers product sheet",
            filename=source,
            reason=f"found {len(matches)}",
        )
    return matches[0]


def _header_width(worksheet: Worksheet) -> int:
    width = 0
    for cell in worksheet[HEADER_ROW]:
        if cell.value not in (None, "") and isinstance(cell.column, int):
            width = max(width, cell.column)
    return width


def _reject_values_outside_header(
    worksheet: Worksheet, row_number: int, width: int, source: Path
) -> None:
    for column in range(width + 1, (worksheet.max_column or width) + 1):
        if worksheet.cell(row_number, column).value not in (None, ""):
            raise LegacyXlsWriteError(
                "Approved export has a value outside the Pioneers header columns",
                filename=source,
                sheet=worksheet.title,
                row=row_number,
                column=get_column_letter(column),
            )


def _cell_text(cell: Cell, source: Path, sheet: str) -> str:
    """Cell text as Pioneers stores it. Converted .xls cells are already text."""
    value = cell.value
    location = {
        "filename": source,
        "sheet": sheet,
        "row": cell.row,
        "column": cell.column_letter,
    }
    if value is None:
        return ""
    if cell.data_type == "f":
        raise LegacyXlsWriteError(
            "A formula cannot be written to a Pioneers .xls export",
            reason="Pioneers exports contain values only",
            **location,
        )
    if isinstance(value, str):
        return value
    if isinstance(value, bool):
        # Pioneers writes the فعال column as True / False.
        return "True" if value else "False"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, float):
        if value.is_integer():
            return str(int(value))
        return format(Decimal(repr(value)), "f")
    if isinstance(value, (datetime, date, time)):
        raise LegacyXlsWriteError(
            "A date cell cannot be written to a Pioneers .xls export",
            reason="the Pioneers text format for dates is unknown",
            **location,
        )
    raise LegacyXlsWriteError(
        "Unsupported cell value in the approved export",
        reason=type(value).__name__,
        **location,
    )


def _publish(payload: bytes, output: Path, *, expected: list[list[str]]) -> None:
    """Write beside ``output``, verify the file, then move it into place."""
    output.parent.mkdir(parents=True, exist_ok=True)
    handle, temp_name = tempfile.mkstemp(
        prefix=".legacy-", suffix=".xls", dir=output.parent
    )
    temp = Path(temp_name)
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(payload)
        _verify(temp, expected)
        os.replace(temp, output)
    finally:
        temp.unlink(missing_ok=True)


def _verify(path: Path, expected: list[list[str]]) -> None:
    data = path.read_bytes()
    if detect_workbook_format(data) is not WorkbookFormat.PIONEERS_HTML_XLS:
        raise LegacyXlsWriteError(
            "Written file is not recognized as a Pioneers HTML .xls",
            output=path,
        )
    try:
        written = read_pioneers_html_xls_rows(path)
    except PioneersExcelError as exc:
        raise LegacyXlsWriteError(
            "Written Pioneers .xls cannot be read back",
            output=path,
            reason=str(exc),
        ) from exc
    if written != expected:
        raise LegacyXlsWriteError(
            "Written Pioneers .xls does not contain the approved export cells",
            output=path,
        )
