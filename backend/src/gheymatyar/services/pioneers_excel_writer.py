"""Write approved final sale prices into a Pioneers-compatible workbook.

The writer loads the original workbook with openpyxl and keeps only the
product rows named by the update list. Within each retained row it changes
only the ``نرخ فروش اصلی`` cell. Unselected product rows are removed, not
hidden. The source file is never saved.

The product sheet is chosen from its headers, not from a fixed sheet title.
Exactly one worksheet must contain ``کد کالا``, ``نـــام کــالا``, and
``نرخ فروش اصلی`` once each on row 1.

Each update names a row in the source workbook. The writer checks the product
name on that row, and the product code when one was supplied, then writes
``نرخ فروش اصلی`` in whichever column carries that header. In the inspected
export that header is column AK; the header is what selects the cell.

This operation stays in memory and in the workbook files. It does not stage
the product list in SQLite. Prices are whole-number text such as ``4610000``.
"""

from __future__ import annotations

import hashlib
import os
import re
import tempfile
import xml.etree.ElementTree as ET
import zipfile
from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, Mapping, Sequence

from openpyxl import load_workbook
from openpyxl.cell.cell import Cell
from openpyxl.formula.tokenizer import Token, Tokenizer
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
# A second sheet can list products without the sale-price header.
_IDENTITY_HEADERS: tuple[str, ...] = (HEADER_CODE, HEADER_NAME)

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
    exported_row_count: int
    content_sha256: str
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
        _retain_approved_product_rows(
            workbook,
            worksheet,
            [row_number for _update, row_number, _old in planned],
        )
        _filter_extra_catalogs(workbook, worksheet, planned)
        _reject_cached_product_objects(workbook)
        exported_row_count = _publish_workbook(
            workbook,
            output,
            planned,
            source=source,
            sheet_name=worksheet.title,
            name_column=name_column,
            code_column=code_column,
            price_column=price_column,
        )
    finally:
        if workbook is not None:
            workbook.close()

    return ExcelUpdateResult(
        source_path=str(source.resolve()),
        output_path=str(output.resolve()),
        updated_count=len(planned),
        exported_row_count=exported_row_count,
        content_sha256=hashlib.sha256(output.read_bytes()).hexdigest(),
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
    seen_rows: dict[int, FinalSalePriceUpdate] = {}
    for index, item in enumerate(updates):
        update = _coerce_update(item, index)
        previous = seen_rows.get(update.row_number)
        if previous is not None:
            if previous.final_sale_price != update.final_sale_price:
                raise DuplicateUpdateError(
                    "conflicting final sale prices for the same Pioneers product",
                    row=update.row_number,
                    pioneers_code=update.pioneers_code,
                    reason=(
                        f"row {update.row_number} is requested at "
                        f"{previous.final_sale_price} and {update.final_sale_price}"
                    ),
                )
            continue
        seen_rows[update.row_number] = update
        parsed.append(update)
    _reject_ambiguous_identities(parsed)
    return parsed


def _reject_ambiguous_identities(updates: Sequence[FinalSalePriceUpdate]) -> None:
    """One source row per product code, and per name when no code was given."""
    by_code: dict[str, FinalSalePriceUpdate] = {}
    by_name: dict[str, FinalSalePriceUpdate] = {}
    for update in updates:
        code = (update.pioneers_code or "").strip()
        if code:
            previous = by_code.get(code)
            if previous is not None and previous.row_number != update.row_number:
                raise DuplicateUpdateError(
                    "selected Pioneers product cannot be identified uniquely",
                    row=update.row_number,
                    pioneers_code=code,
                    reason=(
                        f"code {code} is on rows "
                        f"{previous.row_number} and {update.row_number}"
                    ),
                )
            by_code[code] = update
            continue
        name = _normalize_identity_text(update.pioneers_name)
        previous_name = by_name.get(name)
        if previous_name is not None and previous_name.row_number != update.row_number:
            raise DuplicateUpdateError(
                "selected Pioneers product cannot be identified uniquely",
                row=update.row_number,
                reason=(
                    f"name {update.pioneers_name!r} is on rows "
                    f"{previous_name.row_number} and {update.row_number}"
                ),
            )
        by_name[name] = update


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


_CELL_REF = re.compile(r"^(\$?)([A-Z]{1,3})(\$?)(\d+)$")


def _retain_approved_product_rows(
    workbook: Workbook,
    worksheet: Worksheet,
    keep_rows: Sequence[int],
    *,
    header_row: int = HEADER_ROW,
) -> None:
    """Drop every product row that was not approved and clear stale artifacts.

    Approved rows stay in their original order and move up under the header.
    Formulas, single-row merges, and row heights move with those rows.
    Hidden rows, blank rows, tables, filters, and named ranges that pointed at
    the full product list are removed so Pioneers cannot import them.
    """
    keep = set(keep_rows)
    if not keep or len(keep) != len(keep_rows):
        raise PioneersExcelWriteError(
            "selected Pioneers product cannot be identified uniquely",
            sheet=worksheet.title,
            reason="approved rows are missing or repeated",
        )
    ordered = sorted(keep)
    row_map = {
        old: header_row + offset for offset, old in enumerate(ordered, start=1)
    }
    heights = {
        old: worksheet.row_dimensions[old].height for old in ordered
    }
    relocated_merges = _take_relocated_merges(worksheet, row_map, header_row)
    _clear_sheet_artifacts(worksheet)
    max_row = worksheet.max_row or header_row
    row = max_row
    while row > header_row:
        if row in keep:
            row -= 1
            continue
        end = row
        while row > header_row and row not in keep:
            row -= 1
        worksheet.delete_rows(row + 1, end - row)
    expected_max = header_row + len(keep)
    actual_max = worksheet.max_row or header_row
    if actual_max > expected_max:
        worksheet.delete_rows(expected_max + 1, actual_max - expected_max)
    _unhide_used_rows(worksheet, header_row)
    for old, new in row_map.items():
        worksheet.row_dimensions[new].height = heights[old]
    for min_row, max_row_merged, min_col, max_col in relocated_merges:
        worksheet.merge_cells(
            start_row=min_row,
            start_column=min_col,
            end_row=max_row_merged,
            end_column=max_col,
        )
    _remap_sheet_formulas(worksheet, row_map, header_row)
    _drop_sheet_defined_names(workbook, worksheet.title)


def _take_relocated_merges(
    worksheet: Worksheet,
    row_map: dict[int, int],
    header_row: int,
) -> list[tuple[int, int, int, int]]:
    """Unmerge data ranges and remember those that stay on retained rows."""
    relocated: list[tuple[int, int, int, int]] = []
    for merged in list(worksheet.merged_cells.ranges):
        if merged.max_row <= header_row:
            continue
        rows = list(range(merged.min_row, merged.max_row + 1))
        if any(row not in row_map for row in rows):
            worksheet.unmerge_cells(str(merged))
            continue
        new_rows = [row_map[row] for row in rows]
        if max(new_rows) - min(new_rows) + 1 != len(set(new_rows)):
            worksheet.unmerge_cells(str(merged))
            continue
        relocated.append(
            (min(new_rows), max(new_rows), merged.min_col, merged.max_col)
        )
        worksheet.unmerge_cells(str(merged))
    return relocated


def _remap_sheet_formulas(
    worksheet: Worksheet,
    row_map: dict[int, int],
    header_row: int,
) -> None:
    kept_rows = set(row_map.values())
    for (row_idx, col_idx), cell in list(worksheet._cells.items()):
        if row_idx not in kept_rows:
            continue
        if cell.data_type != "f" or not isinstance(cell.value, str):
            continue
        cell.value = _remap_formula(cell.value, row_map, header_row, worksheet.title)


def _remap_formula(
    formula: str,
    row_map: dict[int, int],
    header_row: int,
    sheet_name: str,
) -> str:
    tokenizer = Tokenizer(formula if formula.startswith("=") else f"={formula}")
    parts: list[str] = []
    for token in tokenizer.items:
        if token.type == Token.OPERAND and token.subtype == Token.RANGE:
            parts.append(
                _remap_reference(token.value, row_map, header_row, sheet_name)
            )
        else:
            parts.append(token.value)
    body = "".join(parts)
    return body if body.startswith("=") else f"={body}"


def _remap_reference(
    ref: str,
    row_map: dict[int, int],
    header_row: int,
    sheet_name: str,
) -> str:
    if "!" in ref or "[" in ref:
        raise PioneersExcelWriteError(
            "formula depends on a sheet or workbook reference that cannot be kept",
            sheet=sheet_name,
            reason=ref,
        )
    if ":" in ref:
        left, right = ref.split(":", 1)
        return (
            f"{_remap_cell(left, row_map, header_row, sheet_name, span=ref)}"
            f":{_remap_cell(right, row_map, header_row, sheet_name, span=ref)}"
        )
    return _remap_cell(ref, row_map, header_row, sheet_name)


def _remap_cell(
    ref: str,
    row_map: dict[int, int],
    header_row: int,
    sheet_name: str,
    *,
    span: str | None = None,
) -> str:
    match = _CELL_REF.match(ref)
    if match is None:
        raise PioneersExcelWriteError(
            "formula depends on a named range or reference that cannot be kept",
            sheet=sheet_name,
            reason=ref,
        )
    col_abs, column, row_abs, row_text = match.groups()
    row = int(row_text)
    if span is not None:
        _reject_range_gap(span, row_map, header_row, sheet_name)
    new_row = _map_formula_row(row, row_map, header_row, sheet_name, ref)
    return f"{col_abs}{column}{row_abs}{new_row}"


def _reject_range_gap(
    span: str,
    row_map: dict[int, int],
    header_row: int,
    sheet_name: str,
) -> None:
    left, right = span.split(":", 1)
    left_match = _CELL_REF.match(left)
    right_match = _CELL_REF.match(right)
    if left_match is None or right_match is None:
        raise PioneersExcelWriteError(
            "formula depends on a named range or reference that cannot be kept",
            sheet=sheet_name,
            reason=span,
        )
    start = int(left_match.group(4))
    end = int(right_match.group(4))
    for row in range(min(start, end), max(start, end) + 1):
        if row > header_row and row not in row_map:
            raise PioneersExcelWriteError(
                "formula depends on a product row that is not in the export",
                sheet=sheet_name,
                reason=f"{span} includes row {row}",
            )


def _map_formula_row(
    row: int,
    row_map: dict[int, int],
    header_row: int,
    sheet_name: str,
    ref: str,
) -> int:
    if row <= header_row:
        return row
    mapped = row_map.get(row)
    if mapped is None:
        raise PioneersExcelWriteError(
            "formula depends on a product row that is not in the export",
            sheet=sheet_name,
            reason=f"{ref} references row {row}",
        )
    return mapped


def _filter_extra_catalogs(
    workbook: Workbook,
    primary: Worksheet,
    planned: Sequence[tuple[FinalSalePriceUpdate, int, Decimal | None]],
) -> None:
    """Remove every product row that is not on the primary product sheet.

    Another catalog, including a veryHidden sheet whose headers omit
    ``نرخ فروش اصلی`` or sit below row 15, would otherwise keep unapproved
    products. Those rows are deleted. The header and any title above it stay.
    A sheet with more than one product table is rejected.
    """
    if not planned:
        raise PioneersExcelWriteError("no approved updates available for export")
    for worksheet in workbook.worksheets:
        if worksheet.title == primary.title:
            continue
        header_row = _find_catalog_header_row(worksheet)
        if header_row is None:
            continue
        columns = _header_columns_on_row(worksheet, header_row)
        _require_unique_header(worksheet, columns, HEADER_CODE)
        _require_unique_header(worksheet, columns, HEADER_NAME)
        max_row = worksheet.max_row or header_row
        if max_row > header_row:
            worksheet.delete_rows(header_row + 1, max_row - header_row)
        _clear_sheet_artifacts(worksheet)
        _unhide_used_rows(worksheet, header_row)
        _drop_sheet_defined_names(workbook, worksheet.title)


def _catalog_header_rows(worksheet: Worksheet) -> list[int]:
    """Every row that identifies products by code and name, once each.

    ``نرخ فروش اصلی`` is not required. A hidden sheet headed by ``کد کالا``,
    ``نـــام کــالا``, and another price label is still a product catalog.
    """
    found: list[int] = []
    for cells in worksheet.iter_rows():
        counts: dict[str, int] = defaultdict(int)
        row_index: int | None = None
        for cell in cells:
            if row_index is None and isinstance(cell.row, int):
                row_index = cell.row
            value = cell.value
            if isinstance(value, str) and value.strip() in _IDENTITY_HEADERS:
                counts[value.strip()] += 1
        if row_index is None:
            continue
        if all(counts.get(header) == 1 for header in _IDENTITY_HEADERS):
            found.append(row_index)
    return found


def _find_catalog_header_row(worksheet: Worksheet) -> int | None:
    """Return the only product-header row, at any position on the sheet."""
    rows = _catalog_header_rows(worksheet)
    if len(rows) > 1:
        raise PioneersExcelWriteError(
            "unsupported workbook contains more than one product table",
            sheet=worksheet.title,
        )
    if not rows:
        return None
    return rows[0]


def _header_columns_on_row(worksheet: Worksheet, header_row: int) -> dict[str, list[int]]:
    header_columns: dict[str, list[int]] = defaultdict(list)
    for cell in worksheet[header_row]:
        value = cell.value
        if not isinstance(value, str) or not isinstance(cell.column, int):
            continue
        header = value.strip()
        if header:
            header_columns[header].append(cell.column)
    return header_columns


def _require_unique_header(
    worksheet: Worksheet,
    columns: Mapping[str, Sequence[int]],
    header: str,
) -> int:
    found = list(columns.get(header, []))
    if len(found) != 1:
        raise PioneersExcelWriteError(
            "unsupported workbook contains product headers that cannot be filtered",
            sheet=worksheet.title,
            column=header,
            reason=f"{header} appears {len(found)} times",
        )
    return found[0]


def _reject_cached_product_objects(workbook: Workbook) -> None:
    """Charts and pivot caches can keep the full catalog after rows are deleted."""
    for worksheet in workbook.worksheets:
        if worksheet._charts:
            raise PioneersExcelWriteError(
                "unsupported workbook contains a chart that can retain unapproved products",
                sheet=worksheet.title,
            )
        if worksheet._pivots:
            raise PioneersExcelWriteError(
                "unsupported workbook contains a pivot table that can retain unapproved products",
                sheet=worksheet.title,
            )


def _clear_sheet_artifacts(worksheet: Worksheet) -> None:
    for name in list(worksheet.tables):
        del worksheet.tables[name]
    worksheet.auto_filter.ref = None
    if worksheet.data_validations is not None:
        worksheet.data_validations.dataValidation = []
    rules = getattr(worksheet.conditional_formatting, "_cf_rules", None)
    if rules:
        for sqref in list(rules):
            del worksheet.conditional_formatting[sqref]
    worksheet.print_area = None
    worksheet.print_title_rows = None


def _unhide_used_rows(worksheet: Worksheet, header_row: int = HEADER_ROW) -> None:
    max_row = worksheet.max_row or header_row
    for index in range(1, max_row + 1):
        if index in worksheet.row_dimensions:
            worksheet.row_dimensions[index].hidden = False
    for index in list(worksheet.row_dimensions):
        if isinstance(index, int) and index > max_row:
            del worksheet.row_dimensions[index]


def _drop_sheet_defined_names(workbook: Workbook, sheet_name: str) -> None:
    quoted = f"'{sheet_name}'"
    plain = f"{sheet_name}!"
    doomed: list[str] = []
    for name in list(workbook.defined_names):
        definition = workbook.defined_names[name]
        text = definition.attr_text or ""
        if quoted in text or plain in text:
            doomed.append(name)
    for name in doomed:
        del workbook.defined_names[name]


def _cell_is_blank(value: object) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _product_row_count(worksheet: Worksheet, header_row: int = HEADER_ROW) -> int:
    max_row = worksheet.max_row or header_row
    max_col = worksheet.max_column or 1
    count = 0
    for row_idx in range(header_row + 1, max_row + 1):
        if row_idx in worksheet.row_dimensions and worksheet.row_dimensions[row_idx].hidden:
            raise PioneersExcelWriteError(
                "exported workbook still has a hidden product row",
                sheet=worksheet.title,
                row=row_idx,
            )
        values = [
            worksheet.cell(row_idx, column).value for column in range(1, max_col + 1)
        ]
        if all(_cell_is_blank(value) for value in values):
            raise PioneersExcelWriteError(
                "exported workbook still has a blank product row",
                sheet=worksheet.title,
                row=row_idx,
            )
        count += 1
    return count


def _publish_workbook(
    workbook: Workbook,
    output: Path,
    planned: Sequence[tuple[FinalSalePriceUpdate, int, Decimal | None]],
    *,
    source: Path,
    sheet_name: str,
    name_column: int,
    code_column: int,
    price_column: int,
) -> int:
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
        exported_row_count = _verify_published_workbook(
            temp_path,
            source,
            planned,
            sheet_name=sheet_name,
            name_column=name_column,
            code_column=code_column,
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
    return exported_row_count


def _verify_published_workbook(
    path: Path,
    source: Path,
    planned: Sequence[tuple[FinalSalePriceUpdate, int, Decimal | None]],
    *,
    sheet_name: str,
    name_column: int,
    code_column: int,
    price_column: int,
) -> int:
    """Re-open the saved file and require exactly the approved product rows."""
    saved = load_workbook(path, read_only=False, data_only=False)
    original = load_workbook(source, read_only=False, data_only=False)
    try:
        if sheet_name not in saved.sheetnames:
            raise PioneersExcelWriteError(
                "Saved workbook is missing the Pioneers product sheet",
                filename=path,
                sheet=sheet_name,
            )
        if saved.sheetnames != original.sheetnames:
            raise PioneersExcelWriteError(
                "Saved workbook changed the worksheet list",
                filename=path,
                reason=f"expected {original.sheetnames}, found {saved.sheetnames}",
            )
        worksheet = saved[sheet_name]
        source_sheet = original[sheet_name]
        if list(worksheet.tables):
            raise PioneersExcelWriteError(
                "Saved workbook still contains a product table",
                filename=path,
                sheet=sheet_name,
            )
        _assert_no_sheet_defined_names(saved, sheet_name, path)
        _assert_headers_match(source_sheet, worksheet, path)
        exported_rows = _product_row_count(worksheet)
        located = _locate_exported_rows(
            worksheet,
            planned,
            name_column=name_column,
            code_column=code_column,
            path=path,
        )
        row_map = {source_row: output_row for _update, source_row, output_row in located}
        for update, source_row, output_row in located:
            _assert_retained_row(
                source_sheet,
                worksheet,
                update,
                source_row=source_row,
                output_row=output_row,
                price_column=price_column,
                path=path,
                row_map=row_map,
            )
        approved_codes = {
            (update.pioneers_code or "").strip()
            for update, _row, _old in planned
            if (update.pioneers_code or "").strip()
        }
        approved_names = {
            _normalize_identity_text(update.pioneers_name)
            for update, _row, _old in planned
            if not (update.pioneers_code or "").strip()
        }
        for _update, _source_row, output_row in located:
            retained_code = _sheet_text(worksheet.cell(output_row, code_column).value)
            if retained_code:
                approved_codes.add(retained_code)
            else:
                approved_names.add(
                    _normalize_identity_text(
                        _sheet_text(worksheet.cell(output_row, name_column).value)
                    )
                )
        extra_rows = 0
        for name in original.sheetnames:
            if name == sheet_name:
                continue
            header_row = _find_catalog_header_row(saved[name])
            if header_row is None:
                _assert_sheet_values_match(original[name], saved[name], path)
                continue
            extra_rows += _product_row_count(saved[name], header_row)
        total_rows = exported_rows + extra_rows
        if exported_rows != len(planned) or extra_rows != 0:
            raise PioneersExcelWriteError(
                "exported product row count does not match the approved selection",
                filename=path,
                sheet=sheet_name,
                reason=f"expected {len(planned)} product rows, found {total_rows}",
            )
        _assert_package_product_records(
            path,
            expected_count=len(planned),
            approved_codes=approved_codes,
            approved_names=approved_names,
        )
        return exported_rows
    finally:
        saved.close()
        original.close()


_CELL_COORD = re.compile(r"^([A-Z]+)(\d+)$")


def _assert_package_product_records(
    path: Path,
    *,
    expected_count: int,
    approved_codes: set[str],
    approved_names: set[str],
) -> None:
    """Read the saved package and require one product record per approval.

    Identity cells are the code column, or the name column when the row has no
    code. A sale price that happens to equal an excluded product code is not
    an identity. Chart, pivot, and table parts can still hide a catalog, so
    those parts are rejected.
    """
    with zipfile.ZipFile(path) as archive:
        for name in archive.namelist():
            if name.startswith(("xl/pivot", "xl/charts/")):
                raise PioneersExcelWriteError(
                    "exported workbook still contains a chart or pivot cache",
                    filename=path,
                    reason=name,
                )
            if name.startswith("xl/tables/"):
                raise PioneersExcelWriteError(
                    "Saved workbook still contains a product table",
                    filename=path,
                    reason=name,
                )
        strings = _package_shared_strings(archive)
        records: list[tuple[str, str]] = []
        for name in archive.namelist():
            if "/worksheets/" not in name or not name.endswith(".xml"):
                continue
            records.extend(
                _xml_product_identities(archive.read(name), strings, path, name)
            )
    if len(records) != expected_count:
        raise PioneersExcelWriteError(
            "exported product row count does not match the approved selection",
            filename=path,
            reason=f"expected {expected_count} product rows, found {len(records)}",
        )
    seen: set[tuple[str, str]] = set()
    for kind, value in records:
        identity = (kind, value)
        if identity in seen:
            raise PioneersExcelWriteError(
                "selected Pioneers product cannot be identified uniquely",
                filename=path,
                pioneers_code=value if kind == "code" else None,
                reason=value,
            )
        seen.add(identity)
        if kind == "code" and value not in approved_codes:
            raise PioneersExcelWriteError(
                "exported workbook still contains an unapproved product",
                filename=path,
                pioneers_code=value,
            )
        if kind == "name" and _normalize_identity_text(value) not in approved_names:
            raise PioneersExcelWriteError(
                "exported workbook still contains an unapproved product",
                filename=path,
                reason=value,
            )


def _package_shared_strings(archive: zipfile.ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in archive.namelist():
        return []
    root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
    strings: list[str] = []
    for element in root:
        if _xml_local(element.tag) != "si":
            continue
        strings.append("".join(text.text or "" for text in element.iter() if _xml_local(text.tag) == "t"))
    return strings


def _xml_product_identities(
    payload: bytes,
    shared_strings: list[str],
    path: Path,
    part_name: str,
) -> list[tuple[str, str]]:
    root = ET.fromstring(payload)
    rows: dict[int, dict[str, str]] = {}
    for element in root.iter():
        if _xml_local(element.tag) != "c":
            continue
        column, row_number = _xml_cell_position(element.get("r"))
        if not column or row_number is None:
            continue
        rows.setdefault(row_number, {})[column] = _xml_cell_text(element, shared_strings)
    header_rows = [
        row_number
        for row_number, values in rows.items()
        if _xml_row_has_product_headers(values)
    ]
    if len(header_rows) > 1:
        raise PioneersExcelWriteError(
            "unsupported workbook contains more than one product table",
            filename=path,
            reason=part_name,
        )
    if not header_rows:
        return []
    header_row = header_rows[0]
    header = rows[header_row]
    code_column = _xml_header_column(header, HEADER_CODE, path, part_name)
    name_column = _xml_header_column(header, HEADER_NAME, path, part_name)
    identities: list[tuple[str, str]] = []
    for row_number in sorted(row for row in rows if row > header_row):
        values = rows[row_number]
        if not any(value.strip() for value in values.values()):
            continue
        code = values.get(code_column, "").strip()
        name = values.get(name_column, "").strip()
        if code:
            identities.append(("code", code))
        elif name:
            identities.append(("name", name))
        else:
            raise PioneersExcelWriteError(
                "exported workbook still contains an unapproved product",
                filename=path,
                reason=f"{part_name} row {row_number}",
            )
    return identities


def _xml_header_column(
    header: Mapping[str, str],
    wanted: str,
    path: Path,
    part_name: str,
) -> str:
    """Find a header after trimming. The workbook cell text is left unchanged."""
    matches = [column for column, value in header.items() if value.strip() == wanted]
    if len(matches) != 1:
        raise PioneersExcelWriteError(
            "unsupported workbook contains product headers that cannot be filtered",
            filename=path,
            column=wanted,
            reason=f"{wanted} appears {len(matches)} times in {part_name}",
        )
    return matches[0]


def _xml_row_has_product_headers(values: Mapping[str, str]) -> bool:
    counts: dict[str, int] = defaultdict(int)
    for value in values.values():
        text = value.strip()
        if text in _IDENTITY_HEADERS:
            counts[text] += 1
    return all(counts.get(header) == 1 for header in _IDENTITY_HEADERS)


def _xml_cell_position(ref: str | None) -> tuple[str, int | None]:
    if not ref:
        return "", None
    match = _CELL_COORD.match(ref)
    if match is None:
        return "", None
    return match.group(1), int(match.group(2))


def _xml_cell_text(element: ET.Element, shared_strings: list[str]) -> str:
    kind = element.get("t")
    if kind == "inlineStr":
        return "".join(
            text.text or "" for text in element.iter() if _xml_local(text.tag) == "t"
        )
    value = next(
        (child.text or "" for child in element if _xml_local(child.tag) == "v"),
        "",
    )
    if kind == "s":
        try:
            return shared_strings[int(value)]
        except (ValueError, IndexError):
            return ""
    return value


def _xml_local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _assert_no_sheet_defined_names(
    workbook: Workbook, sheet_name: str, path: Path
) -> None:
    quoted = f"'{sheet_name}'"
    plain = f"{sheet_name}!"
    for name in workbook.defined_names:
        text = workbook.defined_names[name].attr_text or ""
        if quoted in text or plain in text:
            raise PioneersExcelWriteError(
                "Saved workbook still has a named range on the product sheet",
                filename=path,
                sheet=sheet_name,
                reason=name,
            )


def _assert_headers_match(source: Worksheet, output: Worksheet, path: Path) -> None:
    source_cols = source.max_column or 1
    output_cols = output.max_column or 1
    if source_cols != output_cols:
        raise PioneersExcelWriteError(
            "Saved workbook changed the Pioneers column count",
            filename=path,
            reason=f"expected {source_cols} columns, found {output_cols}",
        )
    for column in range(1, source_cols + 1):
        expected = source.cell(HEADER_ROW, column).value
        found = output.cell(HEADER_ROW, column).value
        if expected != found:
            raise PioneersExcelWriteError(
                "Saved workbook changed a Pioneers header",
                filename=path,
                column=get_column_letter(column),
                reason=f"expected {expected!r}, found {found!r}",
            )


def _sheet_text(value: object) -> str:
    if isinstance(value, str):
        return value.strip()
    if value is None:
        return ""
    return str(value).strip()


def _locate_exported_rows(
    worksheet: Worksheet,
    planned: Sequence[tuple[FinalSalePriceUpdate, int, Decimal | None]],
    *,
    name_column: int,
    code_column: int,
    path: Path,
) -> list[tuple[FinalSalePriceUpdate, int, int]]:
    """Find each approved update in the filtered sheet.

    A code locates the row when the update has one. An update without a code
    locates the row by product name, including when that sheet row still has
    its original code.
    """
    max_row = worksheet.max_row or HEADER_ROW
    rows: list[tuple[int, str, str]] = []
    seen_codes: dict[str, int] = {}
    for row_idx in range(HEADER_ROW + 1, max_row + 1):
        code_text = _sheet_text(worksheet.cell(row_idx, code_column).value)
        name_text = _sheet_text(worksheet.cell(row_idx, name_column).value)
        if code_text:
            if code_text in seen_codes:
                raise PioneersExcelWriteError(
                    "selected Pioneers product cannot be identified uniquely",
                    filename=path,
                    row=row_idx,
                    pioneers_code=code_text,
                )
            seen_codes[code_text] = row_idx
        rows.append((row_idx, code_text, name_text))

    located: list[tuple[FinalSalePriceUpdate, int, int]] = []
    used: set[int] = set()
    for update, source_row, _old in planned:
        code = (update.pioneers_code or "").strip()
        if code:
            output_row = seen_codes.get(code)
            if output_row is None:
                raise PioneersExcelWriteError(
                    "Saved workbook is missing an approved product row",
                    filename=path,
                    pioneers_code=code,
                    reason=update.pioneers_name,
                )
        else:
            name_key = _normalize_identity_text(update.pioneers_name)
            matches = [
                row_idx
                for row_idx, _code_text, name_text in rows
                if _normalize_identity_text(name_text) == name_key
            ]
            if len(matches) != 1:
                raise PioneersExcelWriteError(
                    "selected Pioneers product cannot be identified uniquely",
                    filename=path,
                    reason=update.pioneers_name,
                )
            output_row = matches[0]
        if output_row in used:
            raise PioneersExcelWriteError(
                "selected Pioneers product cannot be identified uniquely",
                filename=path,
                row=output_row,
                pioneers_code=update.pioneers_code,
            )
        used.add(output_row)
        located.append((update, source_row, output_row))
    if len(used) != len(rows):
        raise PioneersExcelWriteError(
            "exported product row count does not match the approved selection",
            filename=path,
            reason=f"expected {len(used)} product rows, found {len(rows)}",
        )
    return located


def _assert_retained_row(
    source: Worksheet,
    output: Worksheet,
    update: FinalSalePriceUpdate,
    *,
    source_row: int,
    output_row: int,
    price_column: int,
    path: Path,
    row_map: Mapping[int, int],
) -> None:
    max_col = source.max_column or 1
    expected_price = _price_as_pioneers_text(update.final_sale_price)
    for column in range(1, max_col + 1):
        source_value = source.cell(source_row, column).value
        output_value = output.cell(output_row, column).value
        if column == price_column:
            if output_value != expected_price:
                raise PioneersExcelWriteError(
                    "Saved workbook does not contain the requested final sale price",
                    filename=path,
                    row=output_row,
                    column=get_column_letter(column),
                    pioneers_code=update.pioneers_code,
                    reason=f"expected {expected_price!r}, found {output_value!r}",
                )
            continue
        expected = source_value
        if isinstance(source_value, str) and source_value.startswith("="):
            expected = _remap_formula(
                source_value,
                dict(row_map),
                HEADER_ROW,
                output.title,
            )
        if output_value != expected:
            raise PioneersExcelWriteError(
                "Saved workbook changed a field other than نرخ فروش اصلی",
                filename=path,
                row=output_row,
                column=get_column_letter(column),
                pioneers_code=update.pioneers_code,
                reason=f"expected {expected!r}, found {output_value!r}",
            )


def _assert_sheet_values_match(source: Worksheet, output: Worksheet, path: Path) -> None:
    if (source.max_row, source.max_column) != (output.max_row, output.max_column):
        raise PioneersExcelWriteError(
            "Saved workbook changed a non-product sheet",
            filename=path,
            sheet=source.title,
        )
    max_row = source.max_row or 1
    max_col = source.max_column or 1
    for row_idx in range(1, max_row + 1):
        for column in range(1, max_col + 1):
            left = source.cell(row_idx, column).value
            right = output.cell(row_idx, column).value
            if left != right:
                raise PioneersExcelWriteError(
                    "Saved workbook changed a non-product sheet",
                    filename=path,
                    sheet=source.title,
                    row=row_idx,
                    column=get_column_letter(column),
                )


__all__ = [
    "ExcelUpdateResult",
    "SalePriceChange",
    "update_final_sale_prices",
]
