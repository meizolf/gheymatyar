#!/usr/bin/env python3
"""Verify PioneersExcelParser does not modify a source workbook on disk.

Usage:
  python scripts/verify_pioneers_excel_immutable.py path/to/export.xlsx
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__.strip(), file=sys.stderr)
        return 2

    source = Path(argv[1])
    if not source.is_file():
        print(f"file not found: {source}", file=sys.stderr)
        return 2

    # Import after path checks so --help-style misuse stays light.
    from gheymatyar.parsers import PioneersExcelError, PioneersExcelParser

    before = sha256_file(source)
    parse_error: str | None = None
    try:
        result = PioneersExcelParser().parse(source)
        product_count = len(result.products)
        invalid_count = len(result.invalid_rows)
        duplicates = len(result.duplicate_codes)
    except PioneersExcelError as exc:
        product_count = None
        invalid_count = None
        duplicates = None
        parse_error = str(exc)

    after = sha256_file(source)
    unchanged = before == after

    print(f"file: {source}")
    print(f"sha256 before: {before}")
    print(f"sha256 after:  {after}")
    print(f"unchanged: {unchanged}")
    if parse_error is None:
        print(f"products: {product_count}")
        print(f"invalid_rows: {invalid_count}")
        print(f"duplicate_codes: {duplicates}")
    else:
        print(f"parse_error: {parse_error}")

    # Exit 0 only when the file is unchanged AND parsing succeeded.
    # A parse failure with an unchanged hash is still a failure.
    if not unchanged:
        return 1
    if parse_error is not None:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
