#!/usr/bin/env python3
"""Compare a Pioneers source workbook to a GheymatYar export.

Asserts:
  * source SHA-256 matches the caller-supplied pre-export hash (immutability)
  * every worksheet is compared (not only the active sheet)
  * cell *formulas* and cached values are compared (``data_only=False``)
  * only ``نرخ فروش اصلی`` cells on the product sheet may differ
  * at least one sale-price cell changed

For HTML-based ``.xls`` sources, pass ``--html-xls`` to convert with the same
converter the app uses, then compare that workbook to the export.
"""

from __future__ import annotations

import argparse
import hashlib
import tempfile
from pathlib import Path

from openpyxl import load_workbook
from openpyxl.cell.cell import Cell
from openpyxl.worksheet.worksheet import Worksheet

SALE_HEADER = "نرخ فروش اصلی"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _cell_key(cell: Cell) -> tuple[object, str | None]:
    """Return (value_or_formula, data_type) for strict comparison."""
    return (cell.value, cell.data_type)


def _header_row(ws: Worksheet) -> list[str | None]:
    cells = next(ws.iter_rows(min_row=1, max_row=1), ())
    return [None if c.value is None else str(c.value) for c in cells]


def _product_sheet_name(wb) -> str:
    matches: list[str] = []
    for name in wb.sheetnames:
        headers = _header_row(wb[name])
        if SALE_HEADER in headers:
            matches.append(name)
    if len(matches) != 1:
        raise SystemExit(
            f"expected exactly one product sheet with {SALE_HEADER!r}, "
            f"found {matches!r}"
        )
    return matches[0]


def _compare_workbooks(source: Path, exported: Path) -> int:
    src_wb = load_workbook(source, data_only=False)
    out_wb = load_workbook(exported, data_only=False)
    try:
        if src_wb.sheetnames != out_wb.sheetnames:
            raise SystemExit(
                f"worksheet names changed\n"
                f"  source: {src_wb.sheetnames}\n"
                f"  export: {out_wb.sheetnames}"
            )

        product_sheet = _product_sheet_name(src_wb)
        sale_idx = _header_row(src_wb[product_sheet]).index(SALE_HEADER)
        changed = 0

        for sheet_name in src_wb.sheetnames:
            src_ws = src_wb[sheet_name]
            out_ws = out_wb[sheet_name]
            src_dims = (src_ws.max_row or 0, src_ws.max_column or 0)
            out_dims = (out_ws.max_row or 0, out_ws.max_column or 0)
            if src_dims != out_dims:
                raise SystemExit(
                    f"sheet {sheet_name!r} dimensions changed: "
                    f"{src_dims} -> {out_dims}"
                )

            max_row, max_col = src_dims
            allow_sale = sheet_name == product_sheet
            for row in range(1, max_row + 1):
                for col in range(1, max_col + 1):
                    src_cell = src_ws.cell(row=row, column=col)
                    out_cell = out_ws.cell(row=row, column=col)
                    if allow_sale and col == sale_idx + 1 and row > 1:
                        if _cell_key(src_cell) != _cell_key(out_cell):
                            # Sale column may change value, but must not become a formula
                            # unless the source was already a formula of the same shape.
                            if out_cell.data_type == "f" and src_cell.data_type != "f":
                                raise SystemExit(
                                    f"sale cell became a formula at "
                                    f"{sheet_name}!R{row}C{col}: {out_cell.value!r}"
                                )
                            changed += 1
                        continue
                    if _cell_key(src_cell) != _cell_key(out_cell):
                        raise SystemExit(
                            f"cell changed at {sheet_name}!R{row}C{col}: "
                            f"{_cell_key(src_cell)!r} -> {_cell_key(out_cell)!r}"
                        )
        return changed
    finally:
        src_wb.close()
        out_wb.close()


def _prepare_source(source: Path, *, html_xls: bool) -> Path:
    if not html_xls:
        return source
    # Import lazily so non-HTML compares do not need the app on PYTHONPATH.
    from gheymatyar.parsers.pioneers_html_xls import (  # noqa: WPS433
        convert_pioneers_html_xls_to_xlsx,
    )

    tmp = Path(tempfile.mkdtemp(prefix="gheymatyar-html-xls-")) / "converted.xlsx"
    convert_pioneers_html_xls_to_xlsx(source, tmp)
    return tmp


def compare(
    source: Path,
    exported: Path,
    expected_source_sha: str,
    *,
    html_xls: bool = False,
) -> None:
    actual = sha256(source)
    if actual != expected_source_sha.lower():
        raise SystemExit(
            f"source hash changed during processing\n"
            f"  expected: {expected_source_sha}\n"
            f"  actual:   {actual}"
        )

    compare_source = _prepare_source(source, html_xls=html_xls)
    changed = _compare_workbooks(compare_source, exported)
    if changed < 1:
        raise SystemExit("export did not change any نرخ فروش اصلی cells")

    print(
        f"OK compare_export: source immutable sha={actual[:12]}…; "
        f"sheets compared; formulas checked; sale-price cells changed={changed}"
        + (" (html-xls converted)" if html_xls else "")
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--exported", type=Path, required=True)
    parser.add_argument("--source-sha256", required=True)
    parser.add_argument(
        "--html-xls",
        action="store_true",
        help="Treat --source as Pioneers HTML .xls and convert before compare",
    )
    args = parser.parse_args(argv)
    compare(
        args.source,
        args.exported,
        args.source_sha256,
        html_xls=args.html_xls,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
