"""Pars Plast prices from the saved parsplast.co page. No test uses the network."""

from __future__ import annotations

import io
import socket
import ssl
import urllib.error
from decimal import Decimal
from email.message import Message
from pathlib import Path

import pytest
import xlrd

from gheymatyar.services.pioneers_legacy_xls_writer import OLE2_SIGNATURE
from gheymatyar.suppliers import website_fetch
from gheymatyar.suppliers.pars_plast import (
    ALLOWED_HOSTS,
    WEBSITE_URL,
    ParsPlastWebsiteError,
    parse_price_list_html,
    product_name,
    size_phrase,
)
from gheymatyar.suppliers.website_fetch import (
    FetchedPage,
    WebsiteFetchError,
    _AllowListRedirects,
    check_allowed_url,
    fetch_html,
)

from .conftest import FIXTURES, PARS_PLAST_HTML

HTML = PARS_PLAST_HTML.read_text(encoding="utf-8")
SAMPLE_XLS = FIXTURES / "pioneers" / "pioneers_html_sample.xls"

CATEGORIES = {
    # title: (rows on the page, priced items, excluded rows)
    "اتصالات پارس فیت": (26, 26, 0),
    "لوله و اتصالات استخری پارس آپ": (68, 57, 11),
    "لوله و اتصالات برقی": (17, 17, 0),
    "لوله و اتصالات پارس درین": (19, 19, 0),
    "لوله و اتصالات تهویه غیر فاضلابی": (39, 39, 0),
    "لوله و اتصالات فاضلابی": (148, 148, 0),
}

# Checked against the page by a separate regex extraction (visible price,
# data-price, code, name, size): name on the site, code, size, Rial price,
# and the full name GheymatYar builds.
EXAMPLES = [
    ("3010030007", "۶۳", 1_061_000, "پارس پلاست زانو 45 درجه پارس فیت سایز 63"),
    ("3170870001", "۵۰", 1_260_000, "پارس پلاست بوشن مغزی استخری پارس آپ سایز 50"),
    ("3070530001", "۲۰", 361_000, "پارس پلاست زانو برقی سایز 20"),
    ("3060030005", "۲۰*۱.۵", 4_240_000, "پارس پلاست لوله برقی خم سرد سایز 20 ضخامت 1.5"),
    ("3010770001", "۲۵", 153_000, "پارس پلاست اتصال سرشیلنگی درین سایز 25"),
    ("310190019", "۲۵*۳۲", 236_000, "پارس پلاست تبدیل درین سایز 25*32"),
    ("3020190001", "۶۳،۹۰", 821_000, "پارس پلاست تبدیل هم مرکز (تهویه) سایز 63*90"),
    ("3040010004", "۱۱۰*۲", 37_550_000, "پارس پلاست لوله های تهویه غیرفاضلابی سایز 110 ضخامت 2"),
    ("3010190015", "۶۳،۹۰", 1_069_000, "پارس پلاست تبدیل پارس فاضلابی سایز 63*90"),
    ("3010210004", "۲۵۰ (۱۲ پیچ)", 19_273_000, "پارس پلاست فلنج فاضلابی سایز 250 (12 پیچ)"),
    ("3170880002", "۶۳", 9_560_000, "پارس پلاست مهره ماسوره چسبی استخری پارس آپ سایز 63"),
    ("3510250009", "۱۲۵", 6_439_000, "پارس پلاست موفه فاضلابی سایز 125"),
]


@pytest.fixture(scope="module")
def parsed():
    return parse_price_list_html(HTML, fetched_at="2026-10-27T14:14:28+00:00")


def _by_name(parsed) -> dict:
    return {item.supplier_name: item for item in parsed.items}


def test_every_category_is_read_not_only_the_linked_one(parsed) -> None:
    categories = {c["title"]: (c["rows"], c["items"], c["excluded"]) for c in parsed.source_metadata["categories"]}
    assert categories == CATEGORIES
    assert len(parsed.items) == 306
    assert parsed.source_metadata["excluded_count"] == 11
    assert parsed.source_metadata["page_modified"] == "2026-10-26T09:46:59+03:30"
    assert {c["updated"] for c in parsed.source_metadata["categories"]} == {"2 آبان 1405"}
    # #price-category-8 on the link is «فاضلابی»; the other five are read too.
    assert parsed.source_metadata["categories"][-1]["panel"] == "8"


@pytest.mark.parametrize(("code", "size", "price", "name"), EXAMPLES)
def test_names_sizes_codes_and_rial_prices(parsed, code, size, price, name) -> None:
    item = _by_name(parsed)[name]
    assert item.price == Decimal(price)  # Rial as printed: never ×10, never × pack
    assert item.raw_values["website_code"] == code
    assert item.raw_values["size_text"] == size
    assert item.raw_values["currency"] == "rial"
    assert item.raw_values["price_basis"] == "printed"
    assert item.supplier_code is None  # codes are reference only


def test_pack_quantity_is_kept_but_never_multiplied(parsed) -> None:
    item = _by_name(parsed)["پارس پلاست زانو 45 درجه پارس فیت سایز 63"]
    assert item.raw_values["package_quantity"] == "120"
    assert item.price == Decimal("1061000")


def test_repeated_website_codes_do_not_merge_products(parsed) -> None:
    shared = [i for i in parsed.items if i.raw_values["website_code"] == "3010010015"]
    assert sorted((i.supplier_name, i.price) for i in shared) == [
        ("پارس پلاست زانو 90 درجه پارس فیت سایز 63", Decimal("1218000")),
        ("پارس پلاست سه راه 90 درجه پارس فیت سایز 63", Decimal("1695000")),
        ("پارس پلاست کوپلینگ پارس فیت سایز 63", Decimal("792000")),
    ]
    names = [i.supplier_name for i in parsed.items]
    assert len(names) == len(set(names))
    # The same cap in two families stays two products, each named by family.
    caps = {i.supplier_name for i in parsed.items if i.raw_values["website_code"] == "3020200001"}
    assert caps == {
        "پارس پلاست درپوش تهویه غیر فاضلابی سایز 63",
        "پارس پلاست درپوش فاضلابی سایز 63",
    }
    assert not any(i.raw_values.get("pricing_blockers") for i in parsed.items)


def test_unpriced_rows_are_excluded(parsed) -> None:
    names = " ".join(i.supplier_name for i in parsed.items)
    assert "تبدیل چسبی استخری پارس آپ سایز 90*63" not in names
    assert all(i.price > 0 for i in parsed.items)
    assert any("11 website rows have no price" in w for w in parsed.warnings)


def test_persian_digits_and_separators_are_normalized() -> None:
    assert size_phrase("۶۳،۹۰", is_pipe=False) == "سایز 63*90"
    assert size_phrase("۹۰,۱۱۰,۱۲۵", is_pipe=False) == "سایز 90*110*125"
    assert size_phrase("۳۲،۲۵،،۴۵", is_pipe=False) == "سایز 32*25*45"
    assert size_phrase("۳۲*۱.۸", is_pipe=True) == "سایز 32 ضخامت 1.8"
    assert size_phrase("۳۲*۳", is_pipe=True) == "سایز 32 ضخامت 3"
    assert size_phrase("۲۵*۳۲", is_pipe=False) == "سایز 25*32"
    assert product_name("لوله برقی خم سرد", "برقی", "۲۰*۱.۵") == (
        "پارس پلاست لوله برقی خم سرد سایز 20 ضخامت 1.5"
    )


def _assert_rejected(html: str, match: str) -> None:
    with pytest.raises(ParsPlastWebsiteError, match=match):
        parse_price_list_html(html)


def test_structure_changes_fail_safely() -> None:
    first_row = HTML.index("data-pzp-product-row")
    row_end = HTML.index("</tr>", first_row) + len("</tr>")
    row_start = HTML.rindex("<tr", 0, first_row)
    cases = {
        "renamed column": (HTML.replace("سایز (mm)", "اندازه", 1), "unexpected columns"),
        "price changed": (HTML.replace('data-price="1061000"', 'data-price="1061001"', 1), "does not match data-price"),
        "row removed": (HTML[:row_start] + HTML[row_end:], "not consecutive|lists"),
        "table removed": (HTML.replace('class="pzp-price-table"', 'class="other-table"', 1), "price tables"),
        "count changed": (HTML.replace("<small>۲۶ محصول</small>", "<small>۲۷ محصول</small>", 1), "lists"),
        "empty page": ("<html><body>maintenance</body></html>", "no price categories"),
    }
    for label, (html, match) in cases.items():
        assert html != HTML or label == "empty page", label
        _assert_rejected(html, match)


class _Response:
    def __init__(self, body: bytes, *, content_type="text/html; charset=UTF-8", url=WEBSITE_URL):
        self._body = io.BytesIO(body)
        self.headers = Message()
        self.headers["Content-Type"] = content_type
        self.headers["Last-Modified"] = "Tue, 27 Oct 2026 10:15:18 GMT"
        self._url = url

    def geturl(self):
        return self._url

    def read(self, size=-1):
        return self._body.read(size)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _Opener:
    def __init__(self, *outcomes):
        self.outcomes = list(outcomes)
        self.calls = 0

    def open(self, request, timeout):
        self.calls += 1
        assert timeout > 0
        assert request.get_header("User-agent").startswith("Gheymat")
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


def _fetch(opener, **kwargs):
    return fetch_html(
        WEBSITE_URL, allowed_hosts=ALLOWED_HOSTS, opener=opener,
        backoff_seconds=0, pace=False, **kwargs,
    )


def test_fetch_reads_the_official_page() -> None:
    page = _fetch(_Opener(_Response(HTML.encode())))
    assert page.html == HTML and page.final_url == WEBSITE_URL
    assert len(page.sha256) == 64 and page.last_modified


def test_network_failures_timeouts_and_retries() -> None:
    timeout = urllib.error.URLError(socket.timeout("timed out"))
    opener = _Opener(timeout, timeout, timeout)
    with pytest.raises(WebsiteFetchError) as caught:
        _fetch(opener, retries=2)
    assert caught.value.kind == "timeout" and opener.calls == 3  # bounded retries

    busy = urllib.error.HTTPError(WEBSITE_URL, 503, "busy", Message(), None)
    opener = _Opener(busy, _Response(HTML.encode()))
    assert _fetch(opener).html == HTML and opener.calls == 2

    # A brief network drop is retried and recovers.
    opener = _Opener(urllib.error.URLError(OSError("no route")), _Response(HTML.encode()))
    assert _fetch(opener).html == HTML and opener.calls == 2

    for error, kind in [
        (urllib.error.HTTPError(WEBSITE_URL, 404, "gone", Message(), None), "http"),
        (urllib.error.HTTPError(WEBSITE_URL, 429, "slow down", Message(), None), "http"),
        (urllib.error.URLError(ssl.SSLCertVerificationError("bad cert")), "tls"),
    ]:
        opener = _Opener(error, _Response(HTML.encode()), _Response(HTML.encode()))
        with pytest.raises(WebsiteFetchError) as caught:
            _fetch(opener)
        assert caught.value.kind == kind
        assert opener.calls == 1  # never retried: 4xx, 429, or a certificate problem

    with pytest.raises(WebsiteFetchError, match="expected an HTML page"):
        _fetch(_Opener(_Response(b"{}", content_type="application/json")))
    with pytest.raises(WebsiteFetchError) as caught:
        _fetch(_Opener(_Response(b"x" * 101)), max_bytes=100)
    assert caught.value.kind == "too_large"


def test_only_the_official_host_over_https_is_allowed() -> None:
    check_allowed_url(WEBSITE_URL, ALLOWED_HOSTS)
    for url in [
        "http://parsplast.co/",
        "https://evil.example/",
        "https://parsplast.co.evil.example/",
        "https://user:pw@parsplast.co/",
        "https://parsplast.co:8443/",
    ]:
        with pytest.raises(WebsiteFetchError) as caught:
            check_allowed_url(url, ALLOWED_HOSTS)
        assert caught.value.kind == "not_allowed"
    handler = _AllowListRedirects(ALLOWED_HOSTS)
    with pytest.raises(WebsiteFetchError):
        handler.redirect_request(None, None, 302, "Found", Message(), "https://evil.example/x")
    # A response that ended up elsewhere is refused too.
    with pytest.raises(WebsiteFetchError):
        _fetch(_Opener(_Response(HTML.encode(), url="https://evil.example/")))
    # Certificates are verified.
    assert ssl.create_default_context().verify_mode == ssl.CERT_REQUIRED


def _page(html: str = HTML) -> FetchedPage:
    return FetchedPage(
        url=WEBSITE_URL, final_url=WEBSITE_URL, html=html,
        fetched_at="2026-10-27T14:14:28+00:00", last_modified=None, sha256="0" * 64,
    )


@pytest.fixture
def website(client):
    """Serve pages from a list instead of the network."""
    pages: list[object] = []

    def fake_fetch(url, *, allowed_hosts):
        assert url == WEBSITE_URL and allowed_hosts == ALLOWED_HOSTS
        outcome = pages.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    client.app.state.processing._website_fetch = fake_fetch
    return pages


def _new_session(client) -> str:
    session_id = client.post("/api/sessions").json()["session_id"]
    with SAMPLE_XLS.open("rb") as handle:
        uploaded = client.post(
            f"/api/sessions/{session_id}/pioneers-excel",
            files={"file": (SAMPLE_XLS.name, handle, "application/vnd.ms-excel")},
        )
    assert uploaded.status_code == 200, uploaded.text
    return session_id


def _fetch_site(client, session_id: str):
    return client.post(
        f"/api/sessions/{session_id}/supplier-website", json={"supplier_key": "pars_plast"}
    )


def test_fetch_api_fills_the_session_with_a_snapshot(client, website) -> None:
    session_id = _new_session(client)
    website.append(_page())

    response = _fetch_site(client, session_id)

    assert response.status_code == 200, response.text
    summary = response.json()
    assert summary["supplier_key"] == "pars_plast"
    assert summary["supplier_confirmed"] is True
    assert summary["supplier_item_count"] == 306
    assert summary["pdf_filename"] is None
    source = summary["supplier_source"]
    assert source["source"] == "website" and source["item_count"] == 306
    assert [c["items"] for c in source["categories"]] == [26, 57, 17, 19, 39, 148]
    session = client.app.state.processing.get_session(session_id)
    assert (session.work_dir / source["snapshot"]).read_text(encoding="utf-8") == HTML

    # The website changing later does not touch this session's prices.
    changed = HTML.replace('data-price="1061000"', 'data-price="9999999"').replace(
        "۱,۰۶۱,۰۰۰", "۹,۹۹۹,۹۹۹"
    )
    website.append(_page(changed))
    other = _new_session(client)
    assert _fetch_site(client, other).status_code == 200
    mine = {i.supplier_name: i.price for i in session.supplier_items}
    assert mine["پارس پلاست زانو 45 درجه پارس فیت سایز 63"] == Decimal("1061000")


def test_failed_fetch_leaves_the_session_unchanged(client, website, azin_pdf: Path) -> None:
    session_id = _new_session(client)
    with azin_pdf.open("rb") as handle:
        assert client.post(
            f"/api/sessions/{session_id}/supplier-pdf",
            data={"supplier_key": "azin_pipe"},
            files={"file": ("azin.pdf", handle, "application/pdf")},
        ).status_code == 200
    before = client.get(f"/api/sessions/{session_id}").json()

    website.extend([
        WebsiteFetchError("timeout", "website did not answer in time"),
        _page("<html><body>maintenance</body></html>"),
    ])
    timeout = _fetch_site(client, session_id)
    broken = _fetch_site(client, session_id)

    assert timeout.status_code == 502 and timeout.json()["detail"]["kind"] == "timeout"
    assert broken.status_code == 502 and broken.json()["detail"]["kind"] == "structure"
    assert client.get(f"/api/sessions/{session_id}").json() == before
    assert client.get("/api/suppliers/pars_plast/mappings").json()["mappings"] == []


def test_pdf_supplier_cannot_be_fetched_from_a_website(client, website) -> None:
    session_id = _new_session(client)
    response = client.post(
        f"/api/sessions/{session_id}/supplier-website", json={"supplier_key": "azin_pipe"}
    )
    assert response.status_code == 400
    assert website == []  # nothing was requested


def _match(client, session_id: str) -> list[dict]:
    matched = client.post(f"/api/sessions/{session_id}/match")
    assert matched.status_code == 200, matched.text
    return matched.json()["candidates"]


ELBOW = "پارس پلاست زانو 45 درجه پارس فیت سایز 63"


def test_saved_mapping_approval_and_three_column_xls(client, website) -> None:
    session_id = _new_session(client)
    website.append(_page())
    assert _fetch_site(client, session_id).status_code == 200
    candidates = _match(client, session_id)
    elbow = next(c for c in candidates if c["supplier_name"] == ELBOW)
    products = client.app.state.processing.get_session(session_id).products
    target = next(p for p in products if p.code and p.name and p.sale_price)

    confirmed = client.post(
        f"/api/sessions/{session_id}/candidates/{elbow['candidate_id']}/confirm-mapping",
        json={"pioneers_row_number": target.row_number, "save": True},
    )
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["new_price"] == "1061000"

    # Approval is still required: nothing is exported before APPROVE.
    assert client.post(f"/api/sessions/{session_id}/export").status_code == 400
    approved = client.post(
        f"/api/sessions/{session_id}/candidates/{elbow['candidate_id']}/review",
        json={"decision": "APPROVE"},
    )
    assert approved.status_code == 200, approved.text
    exported = client.post(f"/api/sessions/{session_id}/export")
    assert exported.status_code == 200, exported.text
    data = client.get(f"/api/sessions/{session_id}/download").content
    assert data.startswith(OLE2_SIGNATURE)
    sheet = xlrd.open_workbook(file_contents=data).sheet_by_index(0)
    assert [sheet.row_values(r) for r in range(sheet.nrows)] == [
        ["کد کالا", "نام کالا", "نرخ فروش اصلی"],
        [target.code, sheet.cell_value(1, 1), 1061000.0],
    ]

    # A new fetch in a new session reuses the saved mapping.
    second = _new_session(client)
    website.append(_page())
    assert _fetch_site(client, second).status_code == 200
    again = next(c for c in _match(client, second) if c["supplier_name"] == ELBOW)
    assert again["status"] == "MATCHED"
    assert again["match_type"] == "SAVED_MAPPING"
    assert again["row_number"] == target.row_number
    assert again["exportable"] is False  # a new session needs a new approval
