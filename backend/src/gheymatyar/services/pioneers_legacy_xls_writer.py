"""Write the approved export as a 3-column Excel 97–2003 ``.xls`` (BIFF8).

Pioneers imports an Excel 97–2003 workbook and updates prices from the
product code and main sale price. It rejects ``.xlsx`` and its own HTML-based
``.xls``. This module writes BIFF8 in an OLE2 container with ``xlwt`` (UTF-16
text), so no Excel or Office is needed on the target PC.

The sheet has exactly three columns, in this order:

* ``کد کالا``: the approved product code, as text (leading zeros kept)
* ``نام کالا``: the product name, exact text from the uploaded file
* ``نرخ فروش اصلی``: the approved final sale price in Rial, as a number

There is one row per approved, changed product and nothing else. Rows come
from the workbook and change list that ``update_final_sale_prices`` has
already verified. Each row is checked against both, and the written file is
read back with ``xlrd`` before it is published.
"""

from __future__ import annotations

import hashlib
import io
import os
import tempfile
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Sequence

import xlrd
import xlwt
from openpyxl import load_workbook
from openpyxl.worksheet.worksheet import Worksheet

from gheymatyar.parsers.pioneers_excel_parser import (
    HEADER_CODE,
    HEADER_NAME,
    HEADER_ROW,
    HEADER_SALE_PRICE,
    PRODUCT_SHEET_NAME,
)
from gheymatyar.services.errors import PioneersExcelWriteError
from gheymatyar.services.pioneers_excel_writer import SalePriceChange

#: OLE2 compound-document signature that starts every BIFF8 ``.xls``.
OLE2_SIGNATURE = bytes.fromhex("D0CF11E0A1B11AE1")
#: The only columns of the export, in this order.
EXPORT_HEADERS = ("کد کالا", "نام کالا", "نرخ فروش اصلی")
#: BIFF8 limits (Excel 97–2003).
MAX_ROWS = 65_536
MAX_TEXT_CHARS = 32_767
# Integers up to 15 digits are exact as an Excel number.
_MAX_PRICE = Decimal(10) ** 15

_REQUIRED_HEADERS = (HEADER_CODE, HEADER_NAME, HEADER_SALE_PRICE)
_HEADER_STYLE = "font: name B Yekan, height 200, bold on; align: horiz center"
_TEXT_STYLE = "font: name B Yekan, height 200"
_PRICE_STYLE = "font: name B Yekan, height 200"


class LegacyXlsWriteError(PioneersExcelWriteError, ValueError):
    """The approved export cannot be written as an Excel 97–2003 ``.xls``."""


@dataclass(frozen=True)
class LegacyXlsResult:
    """A published Excel 97–2003 ``.xls`` export."""

    output_path: str
    exported_row_count: int
    content_sha256: str


@dataclass(frozen=True)
class ExportRow:
    """One product row of the 3-column export."""

    code: str
    name: str
    price: int


def write_pioneers_legacy_xls(
    approved_workbook: str | Path,
    output_path: str | Path,
    changes: Sequence[SalePriceChange],
) -> LegacyXlsResult:
    """Write the approved products as a 3-column Excel 97–2003 ``.xls``.

    ``approved_workbook`` and ``changes`` must both come from the same
    ``update_final_sale_prices`` call.
    """
    source = Path(approved_workbook)
    output = Path(output_path)
    rows = export_rows(source, changes)
    payload = render_pioneers_xls(rows)
    _publish(payload, output, expected=rows)
    return LegacyXlsResult(
        output_path=str(output.resolve()),
        exported_row_count=len(rows),
        content_sha256=hashlib.sha256(payload).hexdigest(),
    )


def export_rows(
    approved_workbook: Path, changes: Sequence[SalePriceChange]
) -> list[ExportRow]:
    """Code, exact name, and price of each approved product, in sheet order."""
    ordered = sorted(changes, key=lambda change: change.row_number)
    for change in ordered:
        if not change.pioneers_code or not change.pioneers_code.strip():
            # Pioneers applies each row by کد کالا; a blank code cannot update.
            raise LegacyXlsWriteError(
                f"Approved product «{change.pioneers_name.strip()}» has no product "
                "code; Pioneers updates prices by product code"
            )
    try:
        workbook = load_workbook(approved_workbook, read_only=False, data_only=False)
    except Exception as exc:  # noqa: BLE001 - wrap openpyxl failures
        raise LegacyXlsWriteError(
            "Failed to open the approved export workbook",
            filename=approved_workbook,
            reason=str(exc),
        ) from exc
    try:
        sheet = _product_sheet(workbook.worksheets, approved_workbook)
        columns = _header_columns(sheet)
        product_rows = [
            row
            for row in range(HEADER_ROW + 1, (sheet.max_row or HEADER_ROW) + 1)
            if any(
                sheet.cell(row, column).value not in (None, "")
                for column in columns.values()
            )
        ]
        if len(product_rows) != len(ordered) or not ordered:
            raise LegacyXlsWriteError(
                "Approved workbook rows do not match the approved changes",
                filename=approved_workbook,
                reason=f"{len(product_rows)} rows, {len(ordered)} changes",
            )
        return [
            _export_row(sheet, row, columns, change, approved_workbook)
            for row, change in zip(product_rows, ordered)
        ]
    finally:
        workbook.close()


def _export_row(
    sheet: Worksheet,
    row: int,
    columns: dict[str, int],
    change: SalePriceChange,
    source: Path,
) -> ExportRow:
    location = {"filename": source, "sheet": sheet.title, "row": row}
    code = change.pioneers_code or ""
    code_cell = sheet.cell(row, columns[HEADER_CODE]).value
    if isinstance(code_cell, str):
        matches = code_cell.strip() == code
    elif isinstance(code_cell, (int, float)) and not isinstance(code_cell, bool):
        # Zero-padded numeric codes reach the change list as padded text.
        matches = code.isdigit() and int(code) == code_cell
    else:
        matches = False
    if not matches:
        raise LegacyXlsWriteError(
            "Approved workbook code does not match the approved change",
            pioneers_code=code,
            **location,
        )
    name = sheet.cell(row, columns[HEADER_NAME]).value
    if not isinstance(name, str) or name.strip() != change.pioneers_name.strip():
        raise LegacyXlsWriteError(
            "Approved workbook name does not match the approved change",
            pioneers_code=code,
            **location,
        )
    price = change.new_final_sale_price
    if price != price.to_integral_value() or not Decimal(0) < price < _MAX_PRICE:
        raise LegacyXlsWriteError(
            "Approved sale price is not a whole Rial amount Excel can hold",
            pioneers_code=code,
            reason=str(price),
            **location,
        )
    written = sheet.cell(row, columns[HEADER_SALE_PRICE]).value
    try:
        written_price = Decimal(str(written).strip()) if written is not None else None
    except InvalidOperation:
        written_price = None
    if written_price != price:
        raise LegacyXlsWriteError(
            "Approved workbook price does not match the approved change",
            pioneers_code=code,
            **location,
        )
    return ExportRow(code=code, name=name, price=int(price))


def render_pioneers_xls(rows: Sequence[ExportRow]) -> bytes:
    """Serialize the header plus product rows as one BIFF8 worksheet."""
    if not rows:
        raise LegacyXlsWriteError("Cannot write a Pioneers .xls without product rows")
    if len(rows) + 1 > MAX_ROWS:
        raise LegacyXlsWriteError(
            "Too many rows for an Excel 97–2003 .xls",
            reason=f"{len(rows) + 1} > {MAX_ROWS}",
        )
    workbook = xlwt.Workbook(encoding="utf-8")
    header_style = xlwt.easyxf(_HEADER_STYLE)
    # "@" is Excel's Text format: codes stay identifiers, not numbers.
    code_style = xlwt.easyxf(_TEXT_STYLE, num_format_str="@")
    name_style = xlwt.easyxf(_TEXT_STYLE)
    price_style = xlwt.easyxf(_PRICE_STYLE, num_format_str="0")
    sheet = workbook.add_sheet(PRODUCT_SHEET_NAME, cell_overwrite_ok=False)
    sheet.cols_right_to_left = True
    for column, header in enumerate(EXPORT_HEADERS):
        sheet.write(0, column, header, header_style)
    for index, row in enumerate(rows, start=1):
        for text in (row.code, row.name):
            if len(text) > MAX_TEXT_CHARS:
                raise LegacyXlsWriteError(
                    "Cell text is too long for an Excel 97–2003 .xls",
                    row=index + 1,
                    pioneers_code=row.code,
                )
        sheet.write(index, 0, row.code, code_style)
        sheet.write(index, 1, row.name, name_style)
        sheet.write(index, 2, float(row.price), price_style)
    stream = io.BytesIO()
    workbook.save(stream)
    return stream.getvalue()


def _product_sheet(worksheets: Sequence[Worksheet], source: Path) -> Worksheet:
    """The only sheet whose row 1 names each Pioneers product header once."""
    matches = [sheet for sheet in worksheets if _has_required_headers(sheet)]
    if len(matches) != 1:
        raise LegacyXlsWriteError(
            "Approved export must have exactly one Pioneers product sheet",
            filename=source,
            reason=f"found {len(matches)}",
        )
    return matches[0]


def _has_required_headers(sheet: Worksheet) -> bool:
    headers = [
        cell.value.strip() for cell in sheet[HEADER_ROW] if isinstance(cell.value, str)
    ]
    return all(headers.count(header) == 1 for header in _REQUIRED_HEADERS)


def _header_columns(sheet: Worksheet) -> dict[str, int]:
    columns: dict[str, int] = {}
    for cell in sheet[HEADER_ROW]:
        if isinstance(cell.value, str) and cell.value.strip() in _REQUIRED_HEADERS:
            columns[cell.value.strip()] = int(cell.column)
    return columns


def _publish(payload: bytes, output: Path, *, expected: list[ExportRow]) -> None:
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


def _verify(payload: bytes, expected: list[ExportRow]) -> None:
    """Read the BIFF8 bytes back and compare every typed cell."""
    if not payload.startswith(OLE2_SIGNATURE):
        raise LegacyXlsWriteError("Rendered file is not an OLE2 Excel 97–2003 .xls")
    try:
        book = xlrd.open_workbook(file_contents=payload)
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
        if sheet.nrows != len(expected) + 1 or sheet.ncols != len(EXPORT_HEADERS):
            raise LegacyXlsWriteError(
                "Rendered .xls has the wrong size",
                reason=f"{sheet.nrows}x{sheet.ncols}",
            )
        header = sheet.row(0)
        if [cell.value for cell in header] != list(EXPORT_HEADERS) or any(
            cell.ctype != xlrd.XL_CELL_TEXT for cell in header
        ):
            raise LegacyXlsWriteError("Rendered .xls header is not the export header")
        for index, row in enumerate(expected, start=1):
            code, name, price = sheet.row(index)
            if not (
                code.ctype == xlrd.XL_CELL_TEXT
                and code.value == row.code
                and name.ctype == xlrd.XL_CELL_TEXT
                and name.value == row.name
                and price.ctype == xlrd.XL_CELL_NUMBER
                and price.value == row.price
            ):
                raise LegacyXlsWriteError(
                    "Rendered .xls row does not match the approved export",
                    row=index + 1,
                    pioneers_code=row.code,
                )
    finally:
        book.release_resources()
