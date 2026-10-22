"""API-wide loopback Host / Origin middleware."""

from __future__ import annotations


def test_foreign_host_rejected_on_settings_get(client) -> None:
    response = client.get("/api/settings", headers={"Host": "evil.example"})
    assert response.status_code == 403
    assert "Host" in response.json()["detail"]


def test_foreign_host_rejected_on_settings_put(client) -> None:
    response = client.put(
        "/api/settings",
        headers={"Host": "evil.example"},
        json={"settings": {"suspicious_percent_threshold": "25"}},
    )
    assert response.status_code == 403


def test_foreign_origin_rejected_on_settings_put(client) -> None:
    response = client.put(
        "/api/settings",
        headers={"Origin": "https://evil.example"},
        json={"settings": {"suspicious_percent_threshold": "25"}},
    )
    assert response.status_code == 403
    assert "cross-origin" in response.json()["detail"]


def test_loopback_settings_still_works(client) -> None:
    response = client.get("/api/settings")
    assert response.status_code == 200
    assert "suspicious_percent_threshold" in response.json()["settings"]
