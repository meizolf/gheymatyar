#!/usr/bin/env python3
"""Assert one export row's نرخ فروش اصلی matches the expected price."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from openpyxl import load_workbook

SALE_HEADER = "نرخ فروش اصلی"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--exported", type=Path, required=True)
    parser.add_argument("--row", type=int, required=True)
    parser.add_argument("--price", required=True)
    args = parser.parse_args(argv)

    wb = load_workbook(args.exported, read_only=True, data_only=True)
    try:
        ws = wb.active
        headers = [c.value for c in next(ws.iter_rows(min_row=1, max_row=1))]
        if SALE_HEADER not in headers:
            raise SystemExit(f"missing column {SALE_HEADER!r}")
        sale_idx = headers.index(SALE_HEADER)
        row_vals = [
            c.value
            for c in next(ws.iter_rows(min_row=args.row, max_row=args.row))
        ]
        got = str(row_vals[sale_idx]).replace(",", "").strip()
        want = str(args.price).replace(",", "").strip()
        if got != want:
            raise SystemExit(f"sale price mismatch at row {args.row}: {got!r} != {want!r}")
    finally:
        wb.close()
    print(f"OK check_export_price: row {args.row} == {want}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
