"""Smoke helpers for packaged export verification."""

from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path

import pytest
from openpyxl import Workbook

REPO_ROOT = Path(__file__).resolve().parents[2]
COMPARE_PATH = REPO_ROOT / "scripts" / "windows" / "compare_export.py"


def _load_compare():
    spec = importlib.util.spec_from_file_location("compare_export", COMPARE_PATH)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture(scope="module")
def compare_mod():
    return _load_compare()


@pytest.fixture(scope="module")
def price_check_mod():
    path = COMPARE_PATH.with_name("check_export_price.py")
    spec = importlib.util.spec_from_file_location("check_export_price", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _write_basic(path: Path, *, sale: str = "100", name: str = "الف") -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "Products"
    ws.append(["کد", "نرخ فروش اصلی", "نام"])
    ws.append(["1", sale, name])
    wb.create_sheet("Meta").append(["note", "unchanged"])
    wb.save(path)
    wb.close()


def test_compare_export_accepts_sale_only_change(tmp_path: Path, compare_mod) -> None:
    source = tmp_path / "src.xlsx"
    exported = tmp_path / "out.xlsx"
    _write_basic(source, sale="100")
    _write_basic(exported, sale="150")
    compare_mod.compare(source, exported, _sha(source))


def test_compare_export_accepts_filtered_product_rows(
    tmp_path: Path, compare_mod
) -> None:
    source = tmp_path / "src.xlsx"
    exported = tmp_path / "out.xlsx"
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "Products"
    ws.append(["کد", "نرخ فروش اصلی", "نام"])
    ws.append(["1", "100", "الف"])
    ws.append(["2", "200", "ب"])
    ws.append(["3", "300", "پ"])
    wb.create_sheet("Meta").append(["note", "unchanged"])
    wb.save(source)
    wb.close()

    wb = Workbook()
    ws = wb.active
    ws.title = "Products"
    ws.append(["کد", "نرخ فروش اصلی", "نام"])
    ws.append(["2", "250", "ب"])
    wb.create_sheet("Meta").append(["note", "unchanged"])
    wb.save(exported)
    wb.close()
    compare_mod.compare(source, exported, _sha(source))


def test_compare_export_rejects_other_column_change(
    tmp_path: Path, compare_mod
) -> None:
    source = tmp_path / "src.xlsx"
    exported = tmp_path / "out.xlsx"
    _write_basic(source, name="الف")
    _write_basic(exported, name="دیگر")
    with pytest.raises(SystemExit, match="cell changed"):
        compare_mod.compare(source, exported, _sha(source))


def test_compare_export_rejects_formula_change(tmp_path: Path, compare_mod) -> None:
    source = tmp_path / "src.xlsx"
    exported = tmp_path / "out.xlsx"

    wb = Workbook()
    ws = wb.active
    ws.title = "Products"
    ws.append(["کد", "نرخ فروش اصلی", "نام"])
    ws.append(["1", "100", "الف"])
    ws["C2"] = "=A2"
    meta = wb.create_sheet("Meta")
    meta["A1"] = "=1+1"
    wb.save(source)
    wb.close()

    wb2 = Workbook()
    ws2 = wb2.active
    ws2.title = "Products"
    ws2.append(["کد", "نرخ فروش اصلی", "نام"])
    ws2.append(["1", "150", "الف"])
    ws2["C2"] = "=A2"
    meta2 = wb2.create_sheet("Meta")
    meta2["A1"] = "=2+2"  # formula changed on non-product sheet
    wb2.save(exported)
    wb2.close()

    with pytest.raises(SystemExit, match="cell changed"):
        compare_mod.compare(source, exported, _sha(source))


def test_compare_export_rejects_extra_sheet_change(
    tmp_path: Path, compare_mod
) -> None:
    source = tmp_path / "src.xlsx"
    exported = tmp_path / "out.xlsx"
    _write_basic(source, sale="100")
    _write_basic(exported, sale="150")
    from openpyxl import load_workbook

    wb = load_workbook(exported)
    wb["Meta"]["B1"] = "tampered"
    wb.save(exported)
    wb.close()

    with pytest.raises(SystemExit, match="cell changed"):
        compare_mod.compare(source, exported, _sha(source))


def test_price_check_finds_compacted_product_on_nonactive_sheet(
    tmp_path: Path, compare_mod, price_check_mod
) -> None:
    source = tmp_path / "src.xlsx"
    exported = tmp_path / "out.xlsx"
    wb = Workbook()
    wb.active.title = "Meta"
    wb.active.append(["unchanged", "=1+1"])
    products = wb.create_sheet("Products")
    products.append(["کد کالا", "نرخ فروش اصلی", "نام"])
    products.append(["unapproved", "100", "الف"])
    products.append(["approved", "200", "ب"])
    wb.save(source)
    products.delete_rows(2)
    products["B2"] = "250.00"
    wb.save(exported)
    wb.close()
    compare_mod.compare(source, exported, _sha(source))
    price_check_mod.check(exported, "approved", "250")


@pytest.mark.parametrize(
    ("code", "sale", "extra_row", "message"),
    [
        ("other", "150", False, "code does not match"),
        ("1", "151", False, "sale price mismatch"),
        ("1", "=150", False, "must not be a formula"),
        ("1", "0", False, "sale price mismatch"),
        ("1", "NaN", False, "sale price mismatch"),
        ("1", "150", True, "exactly one approved product"),
    ],
)
def test_price_check_rejects_wrong_identity_price_or_extra_product(
    tmp_path: Path, price_check_mod, code: str, sale: str,
    extra_row: bool, message: str,
) -> None:
    from openpyxl import load_workbook

    exported = tmp_path / "out.xlsx"
    _write_basic(exported, sale=sale)
    if extra_row:
        wb = load_workbook(exported)
        wb.active.append(["2", "200", "ب"])
        wb.save(exported)
        wb.close()
    with pytest.raises(SystemExit, match=message):
        price_check_mod.check(exported, code, "150")
