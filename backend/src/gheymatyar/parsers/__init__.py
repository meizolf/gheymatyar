"""File parsers for GheymatYar (read-only in Step 4)."""

from gheymatyar.parsers.errors import (
    AmbiguousMappedHeaderError,
    InvalidProductRowError,
    MissingRequiredColumnError,
    PioneersExcelError,
    SheetNotFoundError,
)
from gheymatyar.parsers.pioneers_excel_parser import (
    InvalidProductRow,
    PioneersExcelParser,
    PioneersParseResult,
)
from gheymatyar.parsers.pioneers_html_xls import (
    convert_pioneers_html_xls_to_xlsx,
    read_pioneers_html_xls_rows,
)
from gheymatyar.parsers.workbook_format import WorkbookFormat, detect_workbook_format

__all__ = [
    "AmbiguousMappedHeaderError",
    "InvalidProductRow",
    "InvalidProductRowError",
    "MissingRequiredColumnError",
    "PioneersExcelError",
    "PioneersExcelParser",
    "PioneersParseResult",
    "SheetNotFoundError",
    "WorkbookFormat",
    "convert_pioneers_html_xls_to_xlsx",
    "detect_workbook_format",
    "read_pioneers_html_xls_rows",
]
