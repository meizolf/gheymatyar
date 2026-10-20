"""Detect Pioneers workbook format from file contents (not extension alone)."""

from __future__ import annotations

from enum import Enum


class WorkbookFormat(str, Enum):
    """Supported / recognized on-disk workbook shapes."""

    XLSX = "xlsx"
    PIONEERS_HTML_XLS = "pioneers_html_xls"
    UNSUPPORTED = "unsupported"


# OLE Compound Document (genuine binary .xls / .xlsm container).
_OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
# ZIP local-file header used by Office Open XML (.xlsx).
_ZIP_MAGIC = b"PK\x03\x04"

_HTML_MARKERS = (b"<html", b"<Html", b"<HTML")
_TABLE_MARKERS = (b"<table", b"<Table", b"<TABLE")
# Exact Pioneers headers (UTF-8) used to confirm this is a product-list export.
_HEADER_CODE_UTF8 = "کد کالا".encode("utf-8")
_HEADER_NAME_UTF8 = "نـــام کــالا".encode("utf-8")


def detect_workbook_format(data: bytes) -> WorkbookFormat:
    """Classify bytes as OOXML xlsx, Pioneers HTML-as-xls, or unsupported."""
    if not data:
        return WorkbookFormat.UNSUPPORTED

    # Skip UTF-8 BOM for HTML sniffing only; binary magics are checked first.
    head = data[:8]
    if head.startswith(_ZIP_MAGIC):
        return WorkbookFormat.XLSX
    if head.startswith(_OLE_MAGIC):
        return WorkbookFormat.UNSUPPORTED

    body = data[3:] if data.startswith(b"\xef\xbb\xbf") else data
    sample = body[:65536]
    lower = sample.lower()
    if not any(marker.lower() in lower for marker in _HTML_MARKERS):
        return WorkbookFormat.UNSUPPORTED
    if not any(marker.lower() in lower for marker in _TABLE_MARKERS):
        return WorkbookFormat.UNSUPPORTED
    # Headers may sit beyond the first 64 KiB on pathological files; also
    # check a wider window / full buffer for the required column titles.
    haystack = body if len(body) < 2_000_000 else body[:2_000_000]
    if _HEADER_CODE_UTF8 in haystack and _HEADER_NAME_UTF8 in haystack:
        return WorkbookFormat.PIONEERS_HTML_XLS
    return WorkbookFormat.UNSUPPORTED


def unsupported_format_message(data: bytes) -> str:
    """Human-readable reason when ``detect_workbook_format`` is UNSUPPORTED."""
    if not data:
        return "empty upload is not a supported Pioneers Excel file"
    if data.startswith(_OLE_MAGIC):
        return (
            "binary Excel .xls workbooks are not supported; "
            "export from Pioneers as HTML-based .xls or use .xlsx"
        )
    if data.startswith(_ZIP_MAGIC):
        return "file looks like a ZIP archive but could not be treated as .xlsx"
    body = data[3:] if data.startswith(b"\xef\xbb\xbf") else data
    sample = body[:65536].lower()
    if any(marker.lower() in sample for marker in _HTML_MARKERS):
        return (
            "HTML file is not a Pioneers product-list export "
            "(missing کد کالا / نـــام کــالا headers)"
        )
    return (
        "unsupported Excel format; expected .xlsx or a Pioneers HTML-based .xls export"
    )
