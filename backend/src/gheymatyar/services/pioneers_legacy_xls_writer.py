"""Write the approved-only export as a genuine Excel 97–2003 ``.xls`` (BIFF8).

Pioneers rejects ``.xlsx`` and its own HTML-based ``.xls``. It imported the
HTML export after Microsoft Excel saved it as "Excel 97–2003 Workbook". This
module writes that binary format directly with ``xlwt`` (BIFF8 in an OLE2
container, UTF-16 text), so no Excel or Office is needed on the target PC.

This writer does not pick rows or prices. It renders the workbook that
``update_final_sale_prices`` has already produced and verified, so the same
approved rows, product identities, and ``نرخ فروش اصلی`` text are used. Only
the product sheet is written, with every header column in its original order.

Cell types follow Excel's conversion where nothing is lost: plain numbers
become numbers and ``True`` / ``False`` become booleans. Values Excel would
alter stay exact text. Examples are barcodes with leading zeros
(``015113``), more than 15 significant digits, and decimals with trailing
zeros. Header cells are always exact text, spacing included.

The written file is read back with ``xlrd``. Every typed cell must match
before the file is published.
"""

from __future__ import annotations

import hashlib
import io
import os
import re
import tempfile
from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal
from pathlib import Path
from typing import Sequence

import xlrd
import xlwt
from openpyxl import load_workbook
from openpyxl.cell.cell import Cell
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

from gheymatyar.parsers.pioneers_excel_parser import (
    HEADER_CODE,
    HEADER_NAME,
    HEADER_ROW,
    HEADER_SALE_PRICE,
    PRODUCT_SHEET_NAME,
)
from gheymatyar.services.errors import PioneersExcelWriteError

#: OLE2 compound-document signature that starts every BIFF8 ``.xls``.
OLE2_SIGNATURE = bytes.fromhex("D0CF11E0A1B11AE1")
#: BIFF8 limits (Excel 97–2003).
MAX_ROWS = 65_536
MAX_COLUMNS = 256
MAX_TEXT_CHARS = 32_767

_REQUIRED_HEADERS = (HEADER_CODE, HEADER_NAME, HEADER_SALE_PRICE)
# A number Excel keeps exactly: no sign-only zero, no leading or trailing zeros.
_PLAIN_NUMBER = re.compile(r"^-?(?:0|[1-9][0-9]*)(?:\.[0-9]*[1-9])?$")
_MAX_SIGNIFICANT_DIGITS = 15
_BOOLEANS = {"True": True, "False": False}

# Look of a Pioneers export: B Yekan 10pt, thin borders, centred, a grey bold
# header, and product rows alternating #F5F5F5 / #FFFFFF, starting #F5F5F5.
_HEADER_COLOUR, _ODD_ROW_COLOUR = 0x21, 0x22
xlwt.add_palette_colour("pioneers_header", _HEADER_COLOUR)
xlwt.add_palette_colour("pioneers_odd_row", _ODD_ROW_COLOUR)
_CELL_STYLE = (
    "font: name B Yekan, height 200{bold}; "
    "pattern: pattern solid, fore_colour {colour}; "
    "borders: left thin, right thin, top thin, bottom thin; "
    "align: horiz center, vert center"
)


class LegacyXlsWriteError(PioneersExcelWriteError, ValueError):
    """The approved export cannot be written as an Excel 97–2003 ``.xls``."""


@dataclass(frozen=True)
class LegacyXlsResult:
    """A published Excel 97–2003 ``.xls`` export."""

    output_path: str
    exported_row_count: int
    content_sha256: str


def write_pioneers_legacy_xls(
    approved_workbook: str | Path,
    output_path: str | Path,
) -> LegacyXlsResult:
    """Render a verified approved-only ``.xlsx`` as an Excel 97–2003 ``.xls``.

    ``approved_workbook`` must be the output of ``update_final_sale_prices``.
    Formulas, dates, and values outside the header columns are rejected
    rather than guessed, because a Pioneers export never contains them.
    """
    source = Path(approved_workbook)
    output = Path(output_path)
    rows = _product_rows_as_text(source)
    payload = render_pioneers_xls(rows)
    _publish(payload, output, expected=rows)
    return LegacyXlsResult(
        output_path=str(output.resolve()),
        exported_row_count=len(rows) - 1,
        content_sha256=hashlib.sha256(payload).hexdigest(),
    )


def pioneers_cell_value(text: str, *, header: bool = False) -> str | float | bool:
    """The typed value written for one cell's text (``""`` stays blank)."""
    if header or text == "":
        return text
    if text in _BOOLEANS:
        return _BOOLEANS[text]
    if _PLAIN_NUMBER.match(text):
        digits = text.lstrip("-").replace(".", "").lstrip("0")
        if len(digits) <= _MAX_SIGNIFICANT_DIGITS:
            return float(text)
    return text


def render_pioneers_xls(rows: Sequence[Sequence[str]]) -> bytes:
    """Serialize a header row plus product rows as one BIFF8 worksheet."""
    if len(rows) < 2:
        raise LegacyXlsWriteError("Cannot write a Pioneers .xls without product rows")
    if len(rows) > MAX_ROWS:
        raise LegacyXlsWriteError(
            "Too many rows for an Excel 97–2003 .xls",
            reason=f"{len(rows)} > {MAX_ROWS}",
        )
    width = len(rows[0])
    if width > MAX_COLUMNS:
        raise LegacyXlsWriteError(
            "Too many columns for an Excel 97–2003 .xls",
            reason=f"{width} > {MAX_COLUMNS}",
        )
    workbook = xlwt.Workbook(encoding="utf-8")
    workbook.set_colour_RGB(_HEADER_COLOUR, 0xC0, 0xC0, 0xC0)
    workbook.set_colour_RGB(_ODD_ROW_COLOUR, 0xF5, 0xF5, 0xF5)
    header_style = xlwt.easyxf(_CELL_STYLE.format(bold=", bold on", colour="pioneers_header"))
    row_styles = (
        xlwt.easyxf(_CELL_STYLE.format(bold="", colour="pioneers_odd_row")),
        xlwt.easyxf(_CELL_STYLE.format(bold="", colour="white")),
    )
    sheet = workbook.add_sheet(PRODUCT_SHEET_NAME, cell_overwrite_ok=False)
    sheet.cols_right_to_left = True
    for row_index, row in enumerate(rows):
        if len(row) != width:
            raise LegacyXlsWriteError(
                "Pioneers .xls row width does not match the header",
                row=row_index + 1,
            )
        style = header_style if row_index == 0 else row_styles[(row_index - 1) % 2]
        for column, text in enumerate(row):
            if len(text) > MAX_TEXT_CHARS:
                raise LegacyXlsWriteError(
                    "Cell text is too long for an Excel 97–2003 .xls",
                    row=row_index + 1,
                    column=get_column_letter(column + 1),
                )
            sheet.write(
                row_index, column, pioneers_cell_value(text, header=row_index == 0), style
            )
    stream = io.BytesIO()
    workbook.save(stream)
    return stream.getvalue()


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
    """Verify the bytes, write beside ``output``, then move into place."""
    _verify(payload, expected)
    output.parent.mkdir(parents=True, exist_ok=True)
    handle, temp_name = tempfile.mkstemp(
        prefix=".legacy-", suffix=".xls", dir=output.parent
    )
    temp = Path(temp_name)
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(payload)
        if temp.read_bytes() != payload:
            raise LegacyXlsWriteError("Written .xls differs from the rendered bytes")
        os.replace(temp, output)
    finally:
        temp.unlink(missing_ok=True)


def _verify(payload: bytes, expected: list[list[str]]) -> None:
    """Read the BIFF8 bytes back and compare every typed cell."""
    if not payload.startswith(OLE2_SIGNATURE):
        raise LegacyXlsWriteError("Rendered file is not an OLE2 Excel 97–2003 .xls")
    try:
        book = xlrd.open_workbook(file_contents=payload, on_demand=False)
    except Exception as exc:  # noqa: BLE001 - wrap xlrd failures
        raise LegacyXlsWriteError(
            "Rendered .xls cannot be read back", reason=str(exc)
        ) from exc
    try:
        if book.biff_version != 80 or book.nsheets != 1:
            raise LegacyXlsWriteError(
                "Rendered .xls is not a single-sheet BIFF8 workbook",
                reason=f"biff={book.biff_version} sheets={book.nsheets}",
            )
        sheet = book.sheet_by_index(0)
        if sheet.nrows != len(expected) or sheet.ncols != len(expected[0]):
            raise LegacyXlsWriteError(
                "Rendered .xls has the wrong size",
                reason=f"{sheet.nrows}x{sheet.ncols}",
            )
        for row_index, row in enumerate(expected):
            for column, text in enumerate(row):
                want = pioneers_cell_value(text, header=row_index == 0)
                if not _cell_matches(sheet.cell(row_index, column), want):
                    raise LegacyXlsWriteError(
                        "Rendered .xls cell does not match the approved export",
                        row=row_index + 1,
                        column=get_column_letter(column + 1),
                    )
    finally:
        book.release_resources()


def _cell_matches(cell: xlrd.sheet.Cell, want: str | float | bool) -> bool:
    if want == "" and not isinstance(want, bool):
        return cell.ctype in (xlrd.XL_CELL_EMPTY, xlrd.XL_CELL_BLANK)
    if isinstance(want, bool):
        return cell.ctype == xlrd.XL_CELL_BOOLEAN and bool(cell.value) is want
    if isinstance(want, float):
        return cell.ctype == xlrd.XL_CELL_NUMBER and cell.value == want
    return cell.ctype == xlrd.XL_CELL_TEXT and cell.value == want
