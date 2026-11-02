"""Saving the warning thresholds re-checks the open wizard session at once.

The session is built straight in the store (no PDF parsing or matching): the
candidates stand for an already matched list, as the wizard holds it.
"""

from __future__ import annotations

from decimal import Decimal
from gheymatyar.domain.enums import MatchStatus, ReviewDecision
from gheymatyar.domain.update_candidate import UpdateCandidate
from gheymatyar.repositories.settings_repository import SettingsRepository

from .conftest import PIONEERS_AZIN

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

# label: (percent change, decision, status)
ROWS = {
    "up40": ("40", ReviewDecision.INCLUDE, MatchStatus.MATCHED),
    "down15": ("-15", ReviewDecision.INCLUDE, MatchStatus.MATCHED),
    "up20": ("20", ReviewDecision.INCLUDE, MatchStatus.MATCHED),
    "down5": ("-5", ReviewDecision.INCLUDE, MatchStatus.MATCHED),
    "up60_approved": ("60", ReviewDecision.APPROVE, MatchStatus.MATCHED),
    "up45_approved": ("45", ReviewDecision.APPROVE, MatchStatus.MATCHED),
    "up10_excluded": ("10", ReviewDecision.EXCLUDE, MatchStatus.MATCHED),
    "ambiguous": ("10", ReviewDecision.INCLUDE, MatchStatus.AMBIGUOUS),
}


def _put(client, increase: str, decrease: str):
    return client.put("/api/settings", json={"settings": {
        "price_increase_warning_percent": increase,
        "price_decrease_warning_percent": decrease,
    }})


def _open_session(client) -> str:
    assert _put(client, "50", "20").status_code == 200
    sid = client.post("/api/sessions").json()["session_id"]
    with PIONEERS_AZIN.open("rb") as handle:
        uploaded = client.post(
            f"/api/sessions/{sid}/pioneers-excel", files={"file": ("p.xlsx", handle, XLSX)}
        )
    assert uploaded.status_code == 200, uploaded.text
    session = client.app.state.sessions.require(sid)
    products = [
        p for p in session.products
        if p.code and p.sale_price and p.sale_price % 100 == 0 and p.code not in session.duplicate_codes
    ]
    candidates = []
    for product, (label, (percent, decision, status)) in zip(products, ROWS.items()):
        new = product.sale_price * (100 + Decimal(percent)) / 100
        candidates.append(UpdateCandidate(
            candidate_id=label, row_number=product.row_number, pioneers_code=product.code,
            pioneers_name=product.name, supplier_name=label, old_price=product.sale_price,
            new_price=new, absolute_change=new - product.sale_price,
            percentage_change=Decimal(percent), status=status, review_decision=decision,
            source_currency="rial", price_basis="printed",
        ))
    assert len(candidates) == len(ROWS)
    session.candidates = candidates
    session.supplier_key, session.supplier_confirmed = "azin_pipe", True
    # Matched under +50/-20; the +45 row was approved although it had no warning.
    client.app.state.processing.recheck_price_thresholds(_db(client))
    return sid


def _db(client):
    return client.app.state.database.session_factory()


def _states(client, sid: str) -> dict[str, str | None]:
    rows = client.get(f"/api/sessions/{sid}/candidates").json()["candidates"]
    return {row["candidate_id"]: row["approval"] for row in rows}


def test_saving_thresholds_updates_the_open_session_without_reprocessing(client) -> None:
    sid = _open_session(client)
    assert _states(client, sid) == {
        "up40": "auto", "down15": "auto", "up20": "auto", "down5": "auto",
        "up60_approved": "manual", "up45_approved": "manual",
        "up10_excluded": "excluded", "ambiguous": None,
    }
    before = client.get(f"/api/sessions/{sid}").json()["exportable_count"]

    assert _put(client, "30", "10").status_code == 200

    preview = client.get(f"/api/sessions/{sid}/preview").json()["candidates"]
    by_id = {row["candidate_id"]: row for row in preview}
    assert {k: v["approval"] for k, v in by_id.items()} == {
        "up40": "required", "down15": "required", "up20": "auto", "down5": "auto",
        # Approved while already over the old limit: still the same decision.
        "up60_approved": "manual",
        # Approved with no warning: the new warning needs a fresh approval.
        "up45_approved": "required",
        "up10_excluded": "excluded",
    }
    assert by_id["down15"]["warnings"] == [
        "price change -15.00% exceeds 10% decrease threshold"
    ]
    after = client.get(f"/api/sessions/{sid}").json()["exportable_count"]
    assert (before, after) == (6, 3)
    exported = client.post(f"/api/sessions/{sid}/export")
    assert exported.status_code == 200, exported.text
    assert exported.json()["exported_row_count"] == 3


def test_invalid_save_changes_nothing(client) -> None:
    sid = _open_session(client)
    assert _put(client, "30", "0").status_code == 400
    assert client.get("/api/settings").json()["settings"] == {
        "price_increase_warning_percent": "50", "price_decrease_warning_percent": "20",
    }
    assert _states(client, sid)["up40"] == "auto"


def test_export_reads_the_saved_thresholds_not_the_session_state(client) -> None:
    sid = _open_session(client)
    # Saved behind the session's back (no re-check): export must still apply it.
    with _db(client) as db:
        SettingsRepository(db).set("price_increase_warning_percent", "5")
        SettingsRepository(db).set("price_decrease_warning_percent", "5")
        db.commit()
    exported = client.post(f"/api/sessions/{sid}/export")
    assert exported.status_code == 200, exported.text
    assert exported.json()["exported_row_count"] == 2  # -5% (boundary) and approved +60%
