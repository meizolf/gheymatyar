#!/usr/bin/env python3
"""End-to-end API check against real fixtures (no browser)."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend" / "src"))

from gheymatyar.main import create_app  # noqa: E402

EXCEL = ROOT / "fixtures" / "pioneers" / "pioneers_azin_subset.xlsx"
PDF = ROOT / "fixtures" / "suppliers" / "458_124550609784457.pdf"


def main() -> int:
    if not EXCEL.is_file() or not PDF.is_file():
        print("missing fixtures", file=sys.stderr)
        return 1

    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "e2e.db"
        app = create_app(database_url=f"sqlite:///{db}", mount_spa=False)
        with TestClient(app) as client:
            assert client.get("/api/health").json()["status"] == "ok"
            suppliers = client.get("/api/suppliers").json()
            assert any(s["key"] == "azin_pipe" for s in suppliers)

            sid = client.post("/api/sessions").json()["session_id"]
            with EXCEL.open("rb") as handle:
                excel = client.post(
                    f"/api/sessions/{sid}/pioneers-excel",
                    files={
                        "file": (
                            "p.xlsx",
                            handle,
                            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        )
                    },
                )
            assert excel.status_code == 200, excel.text
            print(f"products={excel.json()['product_count']}")

            with PDF.open("rb") as handle:
                pdf = client.post(
                    f"/api/sessions/{sid}/supplier-pdf",
                    data={"supplier_key": "azin_pipe"},
                    files={"file": ("azin.pdf", handle, "application/pdf")},
                )
            assert pdf.status_code == 200, pdf.text
            print(f"supplier_items={pdf.json()['supplier_item_count']}")

            match = client.post(f"/api/sessions/{sid}/match").json()
            print(
                f"matched={match['matched_count']} "
                f"unmatched={match['unmatched_count']} "
                f"ambiguous={match['ambiguous_count']}"
            )

            preview = client.get(f"/api/sessions/{sid}/preview").json()["candidates"]
            keep = next(c for c in preview if c["status"] == "MATCHED")
            client.post(
                f"/api/sessions/{sid}/candidates/{keep['candidate_id']}/review",
                json={"decision": "APPROVE"},
            )
            for c in preview:
                if c["candidate_id"] == keep["candidate_id"]:
                    continue
                client.post(
                    f"/api/sessions/{sid}/candidates/{c['candidate_id']}/review",
                    json={"decision": "EXCLUDE"},
                )

            export = client.post(f"/api/sessions/{sid}/export")
            assert export.status_code == 200, export.text
            print(f"updated_count={export.json()['updated_count']}")

            download = client.get(f"/api/sessions/{sid}/download")
            assert download.status_code == 200
            assert len(download.content) > 1000
            print("E2E fixture workflow OK")
            return 0


if __name__ == "__main__":
    raise SystemExit(main())
