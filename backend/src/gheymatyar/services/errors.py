"""Errors raised by the Pioneers final-sale-price writer."""

from __future__ import annotations

from pathlib import Path


class PioneersExcelWriteError(Exception):
    """Base error for safe Pioneers Excel price updates."""

    def __init__(
        self,
        message: str,
        *,
        filename: str | Path | None = None,
        output: str | Path | None = None,
        sheet: str | None = None,
        row: int | None = None,
        column: str | None = None,
        pioneers_code: str | None = None,
        reason: str | None = None,
    ) -> None:
        self.filename = str(filename) if filename is not None else None
        self.output = str(output) if output is not None else None
        self.sheet = sheet
        self.row = row
        self.column = column
        self.pioneers_code = pioneers_code
        self.reason = reason
        super().__init__(self._format(message))

    def _format(self, message: str) -> str:
        parts = [message]
        if self.filename:
            parts.append(f"file={self.filename}")
        if self.output:
            parts.append(f"output={self.output}")
        if self.sheet:
            parts.append(f"sheet={self.sheet}")
        if self.row is not None:
            parts.append(f"row={self.row}")
        if self.column:
            parts.append(f"column={self.column}")
        if self.pioneers_code:
            parts.append(f"code={self.pioneers_code}")
        if self.reason:
            parts.append(f"reason={self.reason}")
        if len(parts) == 1:
            return message
        return f"{message} ({', '.join(parts[1:])})"


class SourceOverwriteError(PioneersExcelWriteError):
    """Raised when the output path is the same file as the source workbook."""


class OutputAlreadyExistsError(PioneersExcelWriteError):
    """Raised when the output path already exists. Overwrite is not allowed."""


class TargetPriceColumnMissingError(PioneersExcelWriteError):
    """Raised when نرخ فروش اصلی cannot be identified in the supported format."""


class ProductSheetNotFoundError(PioneersExcelWriteError):
    """Raised when no worksheet contains the Pioneers product headers."""


class AmbiguousProductSheetError(PioneersExcelWriteError):
    """Raised when more than one worksheet matches the Pioneers product headers."""


class ProductNotFoundError(PioneersExcelWriteError):
    """Raised when a requested Pioneers code matches no product row."""


class DuplicateProductCodeError(PioneersExcelWriteError):
    """Raised when a requested code matches more than one product row."""


class DuplicateUpdateError(PioneersExcelWriteError):
    """Raised when the same Pioneers code appears more than once in updates."""


class InvalidPriceError(PioneersExcelWriteError):
    """Raised when a final sale price is missing, non-positive, or not a whole number."""


class UnsafePriceCellError(PioneersExcelWriteError):
    """Raised when a نرخ فروش اصلی cell cannot be safely overwritten."""


class ProductIdentityMismatchError(PioneersExcelWriteError):
    """Raised when the current row does not match the resolved product."""
