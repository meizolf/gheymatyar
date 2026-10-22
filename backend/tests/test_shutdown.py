"""Localhost shutdown endpoint."""

from __future__ import annotations


def _token(client) -> str:
    return client.get("/api/health").json()["control_token"]


def test_shutdown_without_server_handle(client) -> None:
    response = client.post(
        "/api/shutdown",
        headers={"X-GheymatYar-Token": _token(client)},
    )
    assert response.status_code == 400
    assert "python -m gheymatyar" in response.json()["detail"]


def test_shutdown_sets_should_exit(client) -> None:
    class Dummy:
        should_exit = False

    client.app.state.uvicorn_server = Dummy()
    response = client.post(
        "/api/shutdown",
        headers={"X-GheymatYar-Token": _token(client)},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "shutting_down"
    assert client.app.state.uvicorn_server.should_exit is True


def test_shutdown_rejects_missing_token(client) -> None:
    client.app.state.uvicorn_server = type("S", (), {"should_exit": False})()
    response = client.post("/api/shutdown")
    assert response.status_code == 403
    assert "control token" in response.json()["detail"]


def test_shutdown_rejects_bad_token(client) -> None:
    client.app.state.uvicorn_server = type("S", (), {"should_exit": False})()
    response = client.post(
        "/api/shutdown",
        headers={"X-GheymatYar-Token": "not-the-real-token-value-here!!"},
    )
    assert response.status_code == 403


def test_shutdown_rejects_foreign_origin(client) -> None:
    client.app.state.uvicorn_server = type("S", (), {"should_exit": False})()
    response = client.post(
        "/api/shutdown",
        headers={
            "X-GheymatYar-Token": _token(client),
            "Origin": "https://evil.example",
        },
    )
    assert response.status_code == 403
    assert "cross-origin" in response.json()["detail"]


def test_shutdown_rejects_foreign_host(client) -> None:
    client.app.state.uvicorn_server = type("S", (), {"should_exit": False})()
    response = client.post(
        "/api/shutdown",
        headers={
            "Host": "evil.example",
            "X-GheymatYar-Token": _token(client),
        },
    )
    assert response.status_code == 403
