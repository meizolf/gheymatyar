"""Health endpoint tests."""


def test_health_returns_ok(client) -> None:
    response = client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["app"] == "gheymatyar"
    assert body["version"]
    assert body["control_token"]
    assert len(body["control_token"]) >= 16
