"""Pars Plast (پارس زنده‌رود پلاست) prices from its official website.

Pars Plast PDFs are scanned images, so prices are read from the price-list
page on parsplast.co instead. That page shows one tab per product family.
Each tab has one table with the columns ردیف، کد محصول، نام محصول، سایز (mm)،
تعداد در بسته، and قیمت مصرف‌کننده (ریال). Every category is read, whichever
tab the link opens.

Before any row is accepted, the page is checked against what was observed:

* every tab has exactly one panel and table, and every panel has a tab
* the table header is exactly the six expected columns
* row numbers run 1..n in each table
* the number of distinct product names equals the tab's «N محصول» count
* the visible price equals the row's ``data-price``, digit for digit

Any mismatch rejects the whole list. A partial list is never used.

Prices are Rial, as printed, and are never multiplied (not by 10, and not by
the pack quantity). Rows marked «به زودی» or «استعلام قیمت», or with no
price, are excluded and counted.

Website codes repeat across different products: 3010010015 is used for a
63 mm elbow, tee, and coupling. They are kept only as reference. A product is
identified by its full name: brand, product name, family when the name does
not already say it, and size. Two rows with the same full name are blocked
for review, and so are matching rows across families that disagree on price.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from decimal import Decimal
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from gheymatyar.domain.sale_policy import PIONEERS_SALE_CURRENCY
from gheymatyar.domain.supplier_item import SupplierPriceItem
from gheymatyar.services.name_normalization import normalize_digits
from gheymatyar.suppliers.base import BaseSupplierProcessor, SupplierParseResult
from gheymatyar.suppliers.errors import SupplierPdfError
from gheymatyar.suppliers.website_fetch import FetchedPage, fetch_html

BRAND = "پارس پلاست"
#: Official price-list page (لیست-قیمت-پارس-پلاست).
WEBSITE_URL = (
    "https://parsplast.co/"
    "%D9%84%DB%8C%D8%B3%D8%AA-%D9%82%DB%8C%D9%85%D8%AA-"
    "%D9%BE%D8%A7%D8%B1%D8%B3-%D9%BE%D9%84%D8%A7%D8%B3%D8%AA/"
)
ALLOWED_HOSTS = frozenset({"parsplast.co", "www.parsplast.co"})
EXPECTED_HEADERS = (
    "ردیف",
    "کد محصول",
    "نام محصول",
    "سایز (mm)",
    "تعداد در بسته",
    "قیمت مصرف‌کننده (ریال)",
)
_CELL_LABELS = ("ردیف", "کد محصول", "نام محصول", "سایز", "تعداد در بسته", "قیمت مصرف‌کننده")
_UNAVAILABLE = ("استعلام قیمت", "به زودی")
_FAMILY_PREFIXES = ("لوله و اتصالات ", "اتصالات ")
# Family words too generic to show which family a product belongs to.
_GENERIC_FAMILY_WORDS = {"پارس"}
_PRICE_TEXT = re.compile(r"^([0-9][0-9,٬]*)\s*ریال$")
_SIZE_SEPARATORS = re.compile(r"[*،,٬]+")
_PIPE_SIZE = re.compile(r"^(\d+(?:\.\d+)?)\s*\*\s*(\d+(?:\.\d+)?)$")

DUPLICATE_IDENTITY_BLOCKER = (
    "website lists this product more than once with the same name and size; "
    "review the website before export"
)
CROSS_FAMILY_PRICE_BLOCKER = (
    "website lists the same code, product, and size in another family at a "
    "different price; review the website before export"
)


class ParsPlastWebsiteError(SupplierPdfError):
    """The website page is not the price list structure that was verified."""


def _text(value: str) -> str:
    """Collapse whitespace and drop zero-width joiners used only for layout."""
    return " ".join(value.replace("‏", " ").replace("‎", " ").split())


def _digits(value: str) -> str:
    return normalize_digits(value).replace("٫", ".")


def _compact(value: str) -> str:
    return _digits(value).replace("‌", "").replace(" ", "")


@dataclass
class _Row:
    attrs: dict[str, str]
    cells: dict[str, str] = field(default_factory=dict)


@dataclass
class _Panel:
    panel_id: str
    title: str = ""
    updated: str = ""
    caption: str = ""
    tables: int = 0
    headers: list[str] = field(default_factory=list)
    rows: list[_Row] = field(default_factory=list)


class _PriceListPage(HTMLParser):
    """Collect tabs, panels, and table rows from the price-list markup."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tabs: dict[str, dict[str, str]] = {}
        self.panels: list[_Panel] = []
        self.modified_time: str | None = None
        self._tab: str | None = None
        self._panel: _Panel | None = None
        self._section_depth = 0
        self._in_table = False
        self._in_thead = False
        self._row: _Row | None = None
        self._capture: tuple[str, int, list[str], Any] | None = None

    # A capture collects text until the element that started it closes.
    def _start_capture(self, tag: str, sink: Any) -> None:
        self._capture = (tag, 1, [], sink)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {key: (value or "") for key, value in attrs}
        if self._capture is not None:
            ctag, depth, parts, sink = self._capture
            if tag == ctag:
                self._capture = (ctag, depth + 1, parts, sink)
            return
        if tag == "meta" and values.get("property") == "article:modified_time":
            self.modified_time = values.get("content") or None
        if tag == "button" and "data-pzp-tab" in values:
            self._tab = values["data-pzp-tab"]
            self.tabs.setdefault(self._tab, {"title": "", "count": ""})
            return
        if self._tab is not None and tag == "span":
            self._start_capture("span", lambda text: self.tabs[self._tab].update(title=text))
            return
        if self._tab is not None and tag == "small":
            self._start_capture("small", lambda text: self.tabs[self._tab].update(count=text))
            return
        if tag == "section":
            if self._panel is not None:
                self._section_depth += 1
            elif "data-pzp-panel" in values:
                self._panel = _Panel(panel_id=values["data-pzp-panel"])
                self.panels.append(self._panel)
                self._section_depth = 1
            return
        panel = self._panel
        if panel is None:
            return
        classes = values.get("class", "").split()
        if tag == "h3" and not panel.title:
            self._start_capture("h3", lambda text: setattr(panel, "title", text))
        elif tag == "div" and "pzp-price-updated" in classes:
            self._start_capture("div", lambda text: setattr(panel, "updated", text))
        elif tag == "table" and "pzp-price-table" in classes:
            panel.tables += 1
            self._in_table = True
        elif self._in_table and tag == "caption":
            self._start_capture("caption", lambda text: setattr(panel, "caption", text))
        elif self._in_table and tag == "thead":
            self._in_thead = True
        elif self._in_table and self._in_thead and tag == "th":
            self._start_capture("th", panel.headers.append)
        elif self._in_table and tag == "tr" and "data-pzp-product-row" in values:
            self._row = _Row(attrs=values)
            panel.rows.append(self._row)
        elif self._row is not None and tag == "td":
            label = values.get("data-label", "")
            row = self._row
            self._start_capture("td", lambda text: row.cells.__setitem__(label, text))

    def handle_endtag(self, tag: str) -> None:
        if self._capture is not None:
            ctag, depth, parts, sink = self._capture
            if tag == ctag:
                if depth == 1:
                    self._capture = None
                    sink(_text("".join(parts)))
                else:
                    self._capture = (ctag, depth - 1, parts, sink)
            return
        if tag == "button":
            self._tab = None
        elif tag == "section" and self._panel is not None:
            self._section_depth -= 1
            if self._section_depth == 0:
                self._panel = None
        elif tag == "table":
            self._in_table = False
        elif tag == "thead":
            self._in_thead = False
        elif tag == "tr":
            self._row = None

    def handle_data(self, data: str) -> None:
        if self._capture is not None:
            self._capture[2].append(data)


def family_label(title: str) -> str:
    """«لوله و اتصالات فاضلابی» → «فاضلابی»."""
    for prefix in _FAMILY_PREFIXES:
        if title.startswith(prefix):
            return title[len(prefix):].strip()
    return title.strip()


def _needs_family(name: str, family: str) -> bool:
    """Add the family unless the product name already names it."""
    words = set(_digits(name).replace("‌", " ").replace("(", " ").replace(")", " ").split())
    distinctive = [w for w in family.split() if w not in _GENERIC_FAMILY_WORDS]
    return not any(word in words for word in distinctive)


def size_phrase(size_text: str, *, is_pipe: bool) -> str:
    """«۳۲*۱.۸» on a pipe → «سایز 32 ضخامت 1.8»; «۶۳،۹۰» → «سایز 63*90»."""
    text = _text(_digits(size_text))
    if is_pipe:
        pipe = _PIPE_SIZE.match(text)
        if pipe:
            return f"سایز {pipe.group(1)} ضخامت {pipe.group(2)}"
    head, paren, tail = text.partition("(")
    parts = [part.strip() for part in _SIZE_SEPARATORS.split(head) if part.strip()]
    sizes = "*".join(parts) if parts else head.strip()
    extra = f" ({tail.strip()}" if paren else ""
    return f"سایز {sizes}{extra}".strip()


def product_name(name: str, family: str, size_text: str) -> str:
    """One complete name: brand, product, family when needed, and size."""
    clean = _text(_digits(name))
    pieces = [BRAND, clean]
    if family and _needs_family(clean, family):
        pieces.append(family)
    pieces.append(size_phrase(size_text, is_pipe=clean.startswith("لوله")))
    return " ".join(pieces)


def _price(text: str) -> Decimal | None:
    match = _PRICE_TEXT.match(_text(_digits(text)))
    if not match:
        return None
    return Decimal(match.group(1).replace(",", "").replace("٬", ""))


def _is_unavailable(code: str, price_text: str, data_price: str) -> bool:
    if any(word in code or word in price_text for word in _UNAVAILABLE):
        return True
    return not data_price.strip() and _price(price_text) is None


def parse_price_list_html(
    html: str,
    *,
    source_url: str = WEBSITE_URL,
    fetched_at: str | None = None,
    page_sha256: str | None = None,
    supplier_key: str = "pars_plast",
    display_name: str = "پارس پلاست",
) -> SupplierParseResult:
    """Read every category of the Pars Plast price-list page.

    Raises :class:`ParsPlastWebsiteError` when the page does not have the
    verified structure, so no partial or misread list is ever used.
    """
    page = _PriceListPage()
    try:
        page.feed(html)
        page.close()
    except Exception as exc:  # noqa: BLE001 - html.parser failures
        raise ParsPlastWebsiteError(f"Pars Plast price page could not be read: {exc}") from exc

    if not page.tabs or not page.panels:
        raise ParsPlastWebsiteError("Pars Plast price page has no price categories")
    panel_ids = [panel.panel_id for panel in page.panels]
    if len(set(panel_ids)) != len(panel_ids) or set(panel_ids) != set(page.tabs):
        raise ParsPlastWebsiteError(
            "Pars Plast price tabs and tables do not match "
            f"(tabs {sorted(page.tabs)}, tables {panel_ids})"
        )

    items: list[SupplierPriceItem] = []
    categories: list[dict[str, Any]] = []
    excluded_total = 0
    for panel in page.panels:
        tab = page.tabs[panel.panel_id]
        title = panel.title
        if panel.tables != 1:
            raise ParsPlastWebsiteError(f"category «{title}» has {panel.tables} price tables")
        if not title or tab["title"] != title or panel.caption != f"لیست قیمت {title}":
            raise ParsPlastWebsiteError(f"category «{title or panel.panel_id}» is labelled inconsistently")
        if tuple(panel.headers) != EXPECTED_HEADERS:
            raise ParsPlastWebsiteError(
                f"category «{title}» has unexpected columns: {panel.headers}"
            )
        if not panel.rows:
            raise ParsPlastWebsiteError(f"category «{title}» has no product rows")
        stated = re.fullmatch(r"(\d+)\s*محصول", _text(_digits(tab["count"])))
        names = {_text(row.cells.get("نام محصول", "")) for row in panel.rows}
        if not stated or int(stated.group(1)) != len(names):
            raise ParsPlastWebsiteError(
                f"category «{title}» lists {tab['count']!r} but its table has "
                f"{len(names)} products"
            )
        family = family_label(title)
        priced = excluded = 0
        for position, row in enumerate(panel.rows, start=1):
            if tuple(row.cells) != _CELL_LABELS:
                raise ParsPlastWebsiteError(
                    f"category «{title}» row {position} has unexpected cells"
                )
            number = _digits(row.cells["ردیف"])
            if number != str(position):
                raise ParsPlastWebsiteError(
                    f"category «{title}» row numbers are not consecutive at {position}"
                )
            code = _text(_digits(row.cells["کد محصول"]))
            name = _text(row.cells["نام محصول"])
            size_text = _text(row.cells["سایز"])
            price_text = _text(row.cells["قیمت مصرف‌کننده"])
            data_price = row.attrs.get("data-price", "").strip()
            if _text(row.attrs.get("data-name", "")) != name:
                raise ParsPlastWebsiteError(
                    f"category «{title}» row {position} names disagree"
                )
            if _is_unavailable(code, price_text, data_price):
                excluded += 1
                continue
            price = _price(price_text)
            if price is None or not data_price.isdigit() or Decimal(data_price) != price:
                raise ParsPlastWebsiteError(
                    f"category «{title}» row {position} price «{price_text}» "
                    f"does not match data-price {data_price!r}"
                )
            if price <= 0 or not code or not name or not size_text:
                raise ParsPlastWebsiteError(
                    f"category «{title}» row {position} is missing a code, name, size, or price"
                )
            priced += 1
            items.append(
                SupplierPriceItem(
                    supplier_id=supplier_key,
                    # Website codes repeat across products, so they are kept
                    # only as reference and never identify a product.
                    supplier_code=None,
                    supplier_name=product_name(name, family, size_text),
                    price=price,
                    unit=None,
                    raw_values={
                        "currency": PIONEERS_SALE_CURRENCY,
                        "price_basis": "printed",
                        "tax": "not_stated",
                        "source": "website",
                        "category": title,
                        "website_code": code,
                        "website_name": name,
                        "size_text": size_text,
                        "package_quantity": _text(_digits(row.cells["تعداد در بسته"])),
                        "website_row": position,
                        "website_price_text": price_text,
                    },
                )
            )
        excluded_total += excluded
        categories.append(
            {
                "panel": panel.panel_id,
                "title": title,
                "rows": len(panel.rows),
                "items": priced,
                "excluded": excluded,
                "updated": _text(_digits(panel.updated.replace("به‌روزرسانی:", ""))),
            }
        )

    if not items:
        raise ParsPlastWebsiteError("Pars Plast price page has no priced products")
    items, warnings = _flag_conflicts(items)
    if excluded_total:
        warnings.insert(
            0,
            f"{excluded_total} website rows have no price («استعلام قیمت» or «به زودی») "
            "and were excluded",
        )
    return SupplierParseResult(
        supplier_key=supplier_key,
        supplier_display_name=display_name,
        items=items,
        warnings=warnings,
        source_metadata={
            "source": "website",
            "url": source_url,
            "fetched_at": fetched_at,
            "page_modified": page.modified_time,
            "page_sha256": page_sha256,
            "categories": categories,
            "item_count": len(items),
            "excluded_count": excluded_total,
        },
    )


def _flag_conflicts(
    items: list[SupplierPriceItem],
) -> tuple[list[SupplierPriceItem], list[str]]:
    """Block duplicate identities and cross-family price conflicts."""
    warnings: list[str] = []
    by_name = Counter(item.supplier_name for item in items)
    same_product: dict[tuple[str, str, str], set[Decimal]] = defaultdict(set)
    families: dict[tuple[str, str, str], set[str]] = defaultdict(set)
    for item in items:
        raw = item.raw_values
        key = (raw["website_code"], raw["website_name"], _compact(raw["size_text"]))
        same_product[key].add(item.price)
        families[key].add(raw["category"])
    flagged: list[SupplierPriceItem] = []
    for item in items:
        raw = item.raw_values
        key = (raw["website_code"], raw["website_name"], _compact(raw["size_text"]))
        blockers: list[str] = []
        if by_name[item.supplier_name] > 1:
            blockers.append(DUPLICATE_IDENTITY_BLOCKER)
        if len(same_product[key]) > 1:
            blockers.append(CROSS_FAMILY_PRICE_BLOCKER)
        if blockers:
            item = item.model_copy(update={"raw_values": {**raw, "pricing_blockers": blockers}})
        flagged.append(item)
    duplicates = sum(1 for count in by_name.values() if count > 1)
    if duplicates:
        warnings.append(
            f"{duplicates} website product names appear more than once and are blocked for review"
        )
    shared = sum(1 for key, cats in families.items() if len(cats) > 1)
    if shared:
        warnings.append(
            f"{shared} website products are listed in two families with the same code, "
            "size, and price; each is shown under its own family"
        )
    codes = Counter(item.raw_values["website_code"] for item in items)
    reused = {code for code, count in codes.items() if count > 1}
    names_per_code = {
        code: {item.raw_values["website_name"] for item in items if item.raw_values["website_code"] == code}
        for code in reused
    }
    distinct_reuse = sum(1 for names in names_per_code.values() if len(names) > 1)
    if distinct_reuse:
        warnings.append(
            f"{distinct_reuse} website codes are used by different products; "
            "products are told apart by name and size, not by code"
        )
    return flagged, warnings


class ParsPlastWebsiteProcessor(BaseSupplierProcessor):
    """Pars Plast price list read from parsplast.co on user request."""

    supplier_key = "pars_plast"
    display_name = "پارس پلاست"
    source_kind = "website"
    website_url = WEBSITE_URL

    def parse_pdf(self, path: str | Path) -> SupplierParseResult:
        raise SupplierPdfError(
            "Pars Plast PDFs are scanned images; fetch its prices from the website instead"
        )

    def fetch_price_list(self, *, fetch=fetch_html) -> tuple[SupplierParseResult, FetchedPage]:
        """Download the official page and read every category from it."""
        page = fetch(self.website_url, allowed_hosts=ALLOWED_HOSTS)
        result = parse_price_list_html(
            page.html,
            source_url=page.final_url,
            fetched_at=page.fetched_at,
            page_sha256=page.sha256,
            supplier_key=self.supplier_key,
            display_name=self.display_name,
        )
        return result, page
