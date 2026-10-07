"""Parser errors for Pioneers Excel imports."""

from __future__ import annotations

from pathlib import Path


class PioneersExcelError(Exception):
    """Base error for Pioneers Excel parsing failures."""

    def __init__(
        self,
        message: str,
        *,
        filename: str | Path | None = None,
        sheet: str | None = None,
        row: int | None = None,
        column: str | None = None,
        reason: str | None = None,
    ) -> None:
        self.filename = str(filename) if filename is not None else None
        self.sheet = sheet
        self.row = row
        self.column = column
        self.reason = reason
        super().__init__(self._format(message))

    def _format(self, message: str) -> str:
        parts = [message]
        if self.filename:
            parts.append(f"file={self.filename}")
        if self.sheet:
            parts.append(f"sheet={self.sheet}")
        if self.row is not None:
            parts.append(f"row={self.row}")
        if self.column:
            parts.append(f"column={self.column}")
        if self.reason:
            parts.append(f"reason={self.reason}")
        if len(parts) == 1:
            return message
        return f"{message} ({', '.join(parts[1:])})"


class MissingRequiredColumnError(PioneersExcelError):
    """Raised when a required Pioneers header is missing."""


class AmbiguousMappedHeaderError(PioneersExcelError):
    """Raised when a mapped Pioneers header appears more than once."""


class InvalidProductRowError(PioneersExcelError):
    """Raised when a product-like row cannot be turned into PioneersProduct."""


class SheetNotFoundError(PioneersExcelError):
    """Raised when the expected product sheet is not present."""
