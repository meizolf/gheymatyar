"""Write resolved final sale prices into an existing Pioneers workbook.

The writer loads the original workbook with openpyxl and changes only the
``نرخ فروش اصلی`` cell of each requested product. It never rebuilds the
workbook and never saves over the source file.

The product sheet is chosen from its headers, not from a fixed sheet title.
Exactly one worksheet must contain ``کد کالا``, ``نـــام کــالا``, and
``نرخ فروش اصلی`` once each on row 1. Row count is not limited.

Each update names a row in that current workbook. The writer checks the
product name on that row, and the product code when one was supplied, then
writes ``نرخ فروش اصلی`` in whichever column carries that header. In the
inspected export that header is column AK; the header is what selects the cell.

This operation stays in memory and in the workbook files. It does not stage
the product list in SQLite. Prices are whole-number text such as ``4610000``.
"""

from __future__ import annotations

import os
import tempfile
from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, Mapping, Sequence

from openpyxl import load_workbook
from openpyxl.cell.cell import Cell
from openpyxl.utils import get_column_letter
from openpyxl.workbook.workbook import Workbook
from openpyxl.worksheet.worksheet import Worksheet
from pydantic import ValidationError

from gheymatyar.domain.final_sale_price import FinalSalePriceUpdate
from gheymatyar.parsers.errors import InvalidProductRowError
from gheymatyar.parsers.pioneers_excel_parser import (
    HEADER_CODE,
    HEADER_NAME,
    HEADER_ROW,
    HEADER_SALE_PRICE,
    PioneersExcelParser,
    _CellSnapshot,
)
from gheymatyar.services.errors import (
    AmbiguousProductSheetError,
    DuplicateUpdateError,
    InvalidPriceError,
    OutputAlreadyExistsError,
    PioneersExcelWriteError,
    ProductIdentityMismatchError,
    ProductSheetNotFoundError,
    SourceOverwriteError,
    TargetPriceColumnMissingError,
    UnsafePriceCellError,
)

# Headers that identify the product table. The sheet title is not one of them.
_SHEET_MATCH_HEADERS: tuple[str, ...] = (
    HEADER_CODE,
    HEADER_NAME,
    HEADER_SALE_PRICE,
)

_parser = PioneersExcelParser()


@dataclass(frozen=True)
class SalePriceChange:
    """One نرخ فروش اصلی cell that was updated."""

    row_number: int
    pioneers_name: str
    pioneers_code: str | None
    old_final_sale_price: Decimal | None
    new_final_sale_price: Decimal


@dataclass(frozen=True)
class ExcelUpdateResult:
    """Successful all-or-nothing final-sale-price export."""

    source_path: str
    output_path: str
    updated_count: int
    changes: tuple[SalePriceChange, ...]


def update_final_sale_prices(
    source_path: str | Path,
    output_path: str | Path,
    updates: Sequence[FinalSalePriceUpdate | Mapping[str, Any]],
) -> ExcelUpdateResult:
    """Write ``final_sale_price`` into ``نرخ فروش اصلی`` and save a new workbook.

    Every update is validated before any price cell is modified. On failure
    no output file is published and the source file is not saved.
    """
    source = Path(source_path)
    output = Path(output_path)
    _validate_paths(source, output)
    parsed_updates = _parse_updates(updates)

    workbook: Workbook | None = None
    try:
        try:
            workbook = load_workbook(
                filename=source,
                read_only=False,
                data_only=False,
                keep_vba=False,
            )
        except PioneersExcelWriteError:
            raise
        except Exception as exc:  # noqa: BLE001 - wrap openpyxl failures
            raise PioneersExcelWriteError(
                "Failed to open Pioneers Excel workbook",
                filename=source,
                reason=str(exc),
            ) from exc

        worksheet = _resolve_sheet(workbook, source)
        name_column, code_column, price_column = _locate_columns(worksheet, source)
        planned = _plan_changes(
            worksheet,
            parsed_updates,
            name_column=name_column,
            code_column=code_column,
            price_column=price_column,
            source=source,
        )
        _apply_prices(worksheet, planned, price_column=price_column)
        _publish_workbook(
            workbook,
            output,
            planned,
            sheet_name=worksheet.title,
            price_column=price_column,
        )
    finally:
        if workbook is not None:
            workbook.close()

    return ExcelUpdateResult(
        source_path=str(source.resolve()),
        output_path=str(output.resolve()),
        updated_count=len(planned),
        changes=tuple(
            SalePriceChange(
                row_number=row_number,
                pioneers_name=update.pioneers_name,
                pioneers_code=update.pioneers_code,
                old_final_sale_price=old_price,
                new_final_sale_price=update.final_sale_price,
            )
            for update, row_number, old_price in planned
        ),
    )


def _validate_paths(source: Path, output: Path) -> None:
    if not source.is_file():
        raise PioneersExcelWriteError(
            "Pioneers Excel file not found",
            filename=source,
            reason="path does not exist or is not a file",
        )
    if _paths_are_same_file(source, output):
        raise SourceOverwriteError(
            "Refusing to overwrite the source Pioneers workbook",
            filename=source,
            output=output,
            reason="source and output resolve to the same file",
        )
    if output.exists():
        raise OutputAlreadyExistsError(
            "Output file already exists",
            filename=source,
            output=output,
            reason="refusing to overwrite an existing file",
        )
    parent = output.parent
    if parent == Path(".") or not parent.is_dir():
        # output.parent of "file.xlsx" is "." which may exist as cwd; require
        # an explicit destination directory that already exists.
        if not parent.is_dir():
            raise PioneersExcelWriteError(
                "Output directory does not exist",
                filename=source,
                output=output,
                reason=f"missing directory: {parent}",
            )


def _paths_are_same_file(source: Path, output: Path) -> bool:
    source_resolved = source.expanduser().resolve(strict=False)
    output_resolved = output.expanduser().resolve(strict=False)
    if source_resolved == output_resolved:
        return True
    if source_resolved.exists() and output_resolved.exists():
        return os.path.samefile(source_resolved, output_resolved)
    return False


def _parse_updates(
    updates: Sequence[FinalSalePriceUpdate | Mapping[str, Any]],
) -> list[FinalSalePriceUpdate]:
    if isinstance(updates, (str, bytes)) or not isinstance(updates, Sequence):
        raise PioneersExcelWriteError(
            "Price updates must be a sequence",
            reason=f"got {type(updates).__name__}",
        )
    if len(updates) == 0:
        raise PioneersExcelWriteError(
            "At least one final sale price update is required",
            reason="empty update list",
        )

    parsed: list[FinalSalePriceUpdate] = []
    seen: dict[int, Decimal] = {}
    for index, item in enumerate(updates):
        update = _coerce_update(item, index)
        previous = seen.get(update.row_number)
        if previous is not None:
            raise DuplicateUpdateError(
                "Duplicate final sale price update",
                row=update.row_number,
                pioneers_code=update.pioneers_code,
                reason=(
                    f"row {update.row_number} is requested more than once "
                    f"({previous} and {update.final_sale_price})"
                ),
            )
        seen[update.row_number] = update.final_sale_price
        parsed.append(update)
    return parsed


def _coerce_update(
    item: FinalSalePriceUpdate | Mapping[str, Any],
    index: int,
) -> FinalSalePriceUpdate:
    if isinstance(item, FinalSalePriceUpdate):
        return item
    if not isinstance(item, Mapping):
        raise PioneersExcelWriteError(
            "Invalid price update",
            reason=f"update #{index + 1} must be FinalSalePriceUpdate or a mapping",
        )
    code_raw = item.get("pioneers_code")
    price_raw = item.get("final_sale_price")
    row_raw = item.get("row_number")
    try:
        return FinalSalePriceUpdate(
            row_number=row_raw,  # type: ignore[arg-type]
            pioneers_name=item.get("pioneers_name"),  # type: ignore[arg-type]
            pioneers_code=code_raw,
            final_sale_price=price_raw,
        )
    except ValidationError as exc:
        message = str(exc)
        code = code_raw if isinstance(code_raw, str) else None
        row = row_raw if isinstance(row_raw, int) and not isinstance(row_raw, bool) else None
        if "final_sale_price" in message or "float" in message:
            raise InvalidPriceError(
                "Invalid final sale price",
                row=row,
                pioneers_code=code,
                reason=_validation_reason(exc),
            ) from exc
        raise PioneersExcelWriteError(
            "Invalid price update",
            row=row,
            pioneers_code=code,
            reason=_validation_reason(exc),
        ) from exc


def _validation_reason(exc: ValidationError) -> str:
    errors = exc.errors()
    if not errors:
        return str(exc)
    first = errors[0]
    msg = str(first.get("msg", "invalid value"))
    if msg.startswith("Value error, "):
        msg = msg.removeprefix("Value error, ")
    return msg


def _resolve_sheet(workbook: Workbook, source: Path) -> Worksheet:
    """Use the only worksheet whose row 1 has the Pioneers product headers.

    Sheet title is ignored. Hidden worksheets are included. Zero matches and
    several matches are both errors.
    """
    matches = [
        worksheet
        for worksheet in workbook.worksheets
        if _sheet_has_product_headers(worksheet)
    ]
    if len(matches) == 1:
        return matches[0]
    available = ", ".join(workbook.sheetnames) or "(none)"
    required = ", ".join(_SHEET_MATCH_HEADERS)
    if len(matches) > 1:
        found = ", ".join(worksheet.title for worksheet in matches)
        raise AmbiguousProductSheetError(
            "More than one sheet matches the Pioneers product headers",
            filename=source,
            reason=(
                f"matching sheets: {found}. "
                f"required once each on row {HEADER_ROW}: {required}"
            ),
        )
    raise ProductSheetNotFoundError(
        "No sheet matches the Pioneers product headers",
        filename=source,
        reason=(
            f"available sheets: {available}. "
            f"required once each on row {HEADER_ROW}: {required}"
        ),
    )


def _sheet_has_product_headers(worksheet: Worksheet) -> bool:
    header_columns = _header_columns(worksheet)
    return all(
        len(header_columns.get(header, [])) == 1 for header in _SHEET_MATCH_HEADERS
    )


def _header_columns(worksheet: Worksheet) -> dict[str, list[int]]:
    header_columns: dict[str, list[int]] = defaultdict(list)
    for cell in worksheet[HEADER_ROW]:
        value = cell.value
        if not isinstance(value, str):
            continue
        header = value.strip()
        if not header:
            continue
        column = cell.column
        if not isinstance(column, int):
            continue
        header_columns[header].append(column)
    return header_columns


def _locate_columns(worksheet: Worksheet, source: Path) -> tuple[int, int, int]:
    """Return 1-based (name column, code column, نرخ فروش اصلی column).

    The header text selects the column. The inspected export places
    ``نرخ فروش اصلی`` in AK, and a later export may use another column.
    """
    header_columns = _header_columns(worksheet)

    name_columns = header_columns.get(HEADER_NAME, [])
    code_columns = header_columns.get(HEADER_CODE, [])
    price_columns = header_columns.get(HEADER_SALE_PRICE, [])

    if len(name_columns) != 1:
        raise PioneersExcelWriteError(
            f"Missing required Pioneers column:\n{HEADER_NAME}",
            filename=source,
            sheet=worksheet.title,
            column=HEADER_NAME,
            reason="product name header not found exactly once in row 1",
        )

    if len(code_columns) == 0:
        raise PioneersExcelWriteError(
            f"Missing required Pioneers column:\n{HEADER_CODE}",
            filename=source,
            sheet=worksheet.title,
            column=HEADER_CODE,
            reason="required header not found in row 1",
        )
    if len(code_columns) > 1:
        letters = ", ".join(get_column_letter(col) for col in code_columns)
        raise PioneersExcelWriteError(
            f"Ambiguous Pioneers product code column:\n{HEADER_CODE}",
            filename=source,
            sheet=worksheet.title,
            column=HEADER_CODE,
            reason=f"appears in columns {letters}",
        )

    if len(price_columns) == 0:
        raise TargetPriceColumnMissingError(
            f"Missing target price column:\n{HEADER_SALE_PRICE}",
            filename=source,
            sheet=worksheet.title,
            column=HEADER_SALE_PRICE,
            reason=(
                "writer will not guess another price column such as "
                "نرخ آخرین خرید or نرخ بهای تمام شده"
            ),
        )
    if len(price_columns) > 1:
        letters = ", ".join(get_column_letter(col) for col in price_columns)
        raise TargetPriceColumnMissingError(
            f"Ambiguous target price column:\n{HEADER_SALE_PRICE}",
            filename=source,
            sheet=worksheet.title,
            column=HEADER_SALE_PRICE,
            reason=f"appears in columns {letters}",
        )

    return name_columns[0], code_columns[0], price_columns[0]


def _normalize_identity_text(value: str) -> str:
    """Trim and collapse whitespace. Do not fuzzy-match or rewrite letters.

    Persian/Arabic character folding and digit folding are not applied.
    The project does not have a standardized normalizer for those yet.
    """
    return " ".join(value.split())


def _cell_snapshot(cell: Cell) -> _CellSnapshot:
    return _CellSnapshot(
        value=cell.value,
        data_type=str(cell.data_type),
        number_format=str(cell.number_format or "General"),
    )


def _plan_changes(
    worksheet: Worksheet,
    updates: Sequence[FinalSalePriceUpdate],
    *,
    name_column: int,
    code_column: int,
    price_column: int,
    source: Path,
) -> list[tuple[FinalSalePriceUpdate, int, Decimal | None]]:
    max_row = worksheet.max_row or HEADER_ROW
    planned: list[tuple[FinalSalePriceUpdate, int, Decimal | None]] = []
    for update in updates:
        _assert_row_identity(
            worksheet,
            update,
            name_column=name_column,
            code_column=code_column,
            max_row=max_row,
            source=source,
        )
        cell = worksheet.cell(update.row_number, price_column)
        _assert_price_cell_is_writable(
            worksheet,
            cell,
            source=source,
            pioneers_code=update.pioneers_code,
            row_number=update.row_number,
        )
        planned.append(
            (
                update,
                update.row_number,
                _read_existing_price(
                    cell,
                    source=source,
                    pioneers_code=update.pioneers_code,
                    row_number=update.row_number,
                ),
            )
        )
    return planned


def _assert_row_identity(
    worksheet: Worksheet,
    update: FinalSalePriceUpdate,
    *,
    name_column: int,
    code_column: int,
    max_row: int,
    source: Path,
) -> None:
    if update.row_number > max_row:
        raise ProductIdentityMismatchError(
            "Resolved row is outside the current Pioneers worksheet",
            filename=source,
            sheet=worksheet.title,
            row=update.row_number,
            pioneers_code=update.pioneers_code,
            reason=(
                f"row {update.row_number} is past the last worksheet row {max_row}"
            ),
        )

    try:
        actual_name = _parser._parse_name(
            _cell_snapshot(worksheet.cell(update.row_number, name_column))
        )
    except InvalidProductRowError as exc:
        raise ProductIdentityMismatchError(
            "Product name on the resolved row cannot be verified",
            filename=source,
            sheet=worksheet.title,
            row=update.row_number,
            column=HEADER_NAME,
            pioneers_code=update.pioneers_code,
            reason=exc.reason or str(exc),
        ) from exc

    expected_name = _normalize_identity_text(update.pioneers_name)
    found_name = _normalize_identity_text(actual_name) if actual_name else ""
    if actual_name is None or found_name != expected_name:
        raise ProductIdentityMismatchError(
            "Product name does not match the resolved Pioneers row",
            filename=source,
            sheet=worksheet.title,
            row=update.row_number,
            column=HEADER_NAME,
            pioneers_code=update.pioneers_code,
            reason=f"expected {update.pioneers_name!r}, found {actual_name!r}",
        )

    if update.pioneers_code is None:
        return

    try:
        actual_code = _parser._parse_code_or_barcode(
            _cell_snapshot(worksheet.cell(update.row_number, code_column)),
            column=HEADER_CODE,
        )
    except InvalidProductRowError as exc:
        raise ProductIdentityMismatchError(
            "Product code on the resolved row cannot be verified",
            filename=source,
            sheet=worksheet.title,
            row=update.row_number,
            column=HEADER_CODE,
            pioneers_code=update.pioneers_code,
            reason=exc.reason or str(exc),
        ) from exc

    if actual_code != update.pioneers_code:
        raise ProductIdentityMismatchError(
            "Product code does not match the resolved Pioneers row",
            filename=source,
            sheet=worksheet.title,
            row=update.row_number,
            column=HEADER_CODE,
            pioneers_code=update.pioneers_code,
            reason=f"expected {update.pioneers_code!r}, found {actual_code!r}",
        )


def _assert_price_cell_is_writable(
    worksheet: Worksheet,
    cell: Cell,
    *,
    source: Path,
    pioneers_code: str | None,
    row_number: int,
) -> None:
    coordinate = cell.coordinate
    column_letter = (
        get_column_letter(cell.column) if isinstance(cell.column, int) else None
    )
    for merged in worksheet.merged_cells.ranges:
        if coordinate in merged:
            raise UnsafePriceCellError(
                "Refusing to overwrite a merged نرخ فروش اصلی cell",
                filename=source,
                sheet=worksheet.title,
                row=row_number,
                column=column_letter,
                pioneers_code=pioneers_code,
                reason=f"{coordinate} is inside merged range {merged}",
            )

    value = cell.value
    if cell.data_type == "f" or (isinstance(value, str) and value.startswith("=")):
        raise UnsafePriceCellError(
            "Refusing to overwrite a formula in نرخ فروش اصلی",
            filename=source,
            sheet=worksheet.title,
            row=row_number,
            column=column_letter,
            pioneers_code=pioneers_code,
            reason=f"cell {coordinate} contains a formula",
        )
    if cell.data_type == "e":
        raise UnsafePriceCellError(
            "Refusing to overwrite an Excel error in نرخ فروش اصلی",
            filename=source,
            sheet=worksheet.title,
            row=row_number,
            column=column_letter,
            pioneers_code=pioneers_code,
            reason=f"cell {coordinate} contains {value!r}",
        )


def _read_existing_price(
    cell: Cell,
    *,
    source: Path,
    pioneers_code: str | None,
    row_number: int,
) -> Decimal | None:
    value = cell.value
    if value is None:
        return None
    if isinstance(value, str) and not value.strip():
        return None
    if isinstance(value, bool) or isinstance(value, float):
        raise UnsafePriceCellError(
            "نرخ فروش اصلی cell has an unsupported existing value",
            filename=source,
            row=row_number,
            column=get_column_letter(cell.column) if isinstance(cell.column, int) else None,
            pioneers_code=pioneers_code,
            reason=f"unsupported existing type: {type(value).__name__}",
        )
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise UnsafePriceCellError(
                "نرخ فروش اصلی cell has a non-finite existing value",
                column=get_column_letter(cell.column) if isinstance(cell.column, int) else None,
                reason=repr(value),
            )
        return value
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, str):
        try:
            amount = Decimal(value.strip())
        except Exception as exc:  # noqa: BLE001
            raise UnsafePriceCellError(
                "نرخ فروش اصلی cell is not a numeric price",
                row=cell.row if isinstance(cell.row, int) else None,
                column=get_column_letter(cell.column) if isinstance(cell.column, int) else None,
                reason=f"cannot parse existing value {value!r}",
            ) from exc
        if not amount.is_finite():
            raise UnsafePriceCellError(
                "نرخ فروش اصلی cell has a non-finite existing value",
                column=get_column_letter(cell.column) if isinstance(cell.column, int) else None,
                reason=repr(value),
            )
        return amount
    raise UnsafePriceCellError(
        "نرخ فروش اصلی cell has an unsupported existing value",
        column=get_column_letter(cell.column) if isinstance(cell.column, int) else None,
        reason=f"unsupported existing type: {type(value).__name__}",
    )


def _apply_prices(
    worksheet: Worksheet,
    planned: Sequence[tuple[FinalSalePriceUpdate, int, Decimal | None]],
    *,
    price_column: int,
) -> None:
    for update, row_number, _old in planned:
        cell = worksheet.cell(row_number, price_column)
        # Assign only the value. openpyxl keeps number format, font, fill,
        # border, alignment, and protection on the existing cell.
        cell.value = _price_as_pioneers_text(update.final_sale_price)


def _price_as_pioneers_text(amount: Decimal) -> str:
    """Serialize a whole-number price the way the Pioneers export stores it.

    Inspected cells are text (``data_type='s'``), number format ``General``,
    with no decimal point. ``4610000`` is written as ``"4610000"``, never
    ``4610000.0``.
    """
    integral = amount.to_integral_value()
    if integral != amount:
        raise InvalidPriceError(
            "Invalid final sale price",
            reason=f"refusing to round {amount}",
        )
    text = format(integral, "f")
    if "." in text:
        text = text.split(".", 1)[0]
    if text.startswith("+"):
        text = text[1:]
    if not text.isdigit():
        raise InvalidPriceError(
            "Invalid final sale price",
            reason=f"cannot write {amount} as an integer price",
        )
    return text


def _publish_workbook(
    workbook: Workbook,
    output: Path,
    planned: Sequence[tuple[FinalSalePriceUpdate, int, Decimal | None]],
    *,
    sheet_name: str,
    price_column: int,
) -> None:
    """Save to a temp file in the destination directory, then link it into place.

    ``os.link`` fails if the final path already exists, so a racing create
    cannot be overwritten. The source workbook object is saved only to the
    temporary path.
    """
    if output.exists():
        raise OutputAlreadyExistsError(
            "Output file already exists",
            output=output,
            reason="refusing to overwrite an existing file",
        )

    temp_path: Path | None = None
    try:
        fd, raw_name = tempfile.mkstemp(
            prefix=".gheymatyar-sale-price-",
            suffix=".xlsx",
            dir=output.parent,
        )
        os.close(fd)
        temp_path = Path(raw_name)
        workbook.save(temp_path)
        _verify_published_prices(
            temp_path,
            planned,
            sheet_name=sheet_name,
            price_column=price_column,
        )
        try:
            os.link(temp_path, output)
        except FileExistsError as exc:
            raise OutputAlreadyExistsError(
                "Output file already exists",
                output=output,
                reason="refusing to overwrite an existing file",
            ) from exc
    finally:
        if temp_path is not None and temp_path.exists():
            temp_path.unlink()


def _verify_published_prices(
    path: Path,
    planned: Sequence[tuple[FinalSalePriceUpdate, int, Decimal | None]],
    *,
    sheet_name: str,
    price_column: int,
) -> None:
    workbook = load_workbook(path, read_only=False, data_only=False)
    try:
        if sheet_name not in workbook.sheetnames:
            raise PioneersExcelWriteError(
                "Saved workbook is missing the Pioneers product sheet",
                filename=path,
                sheet=sheet_name,
            )
        worksheet = workbook[sheet_name]
        for update, row_number, _old in planned:
            cell = worksheet.cell(row_number, price_column)
            expected = _price_as_pioneers_text(update.final_sale_price)
            if cell.value != expected:
                raise PioneersExcelWriteError(
                    "Saved workbook does not contain the requested final sale price",
                    filename=path,
                    sheet=sheet_name,
                    row=row_number,
                    column=get_column_letter(cell.column) if isinstance(cell.column, int) else None,
                    pioneers_code=update.pioneers_code,
                    reason=f"expected {expected!r}, found {cell.value!r}",
                )
    finally:
        workbook.close()


__all__ = [
    "ExcelUpdateResult",
    "SalePriceChange",
    "update_final_sale_prices",
]
