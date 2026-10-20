"""Localhost shutdown endpoint."""

from __future__ import annotations


def test_shutdown_without_server_handle(client) -> None:
    response = client.post("/api/shutdown")
    assert response.status_code == 400
    assert "python -m gheymatyar" in response.json()["detail"]


def test_shutdown_sets_should_exit(client) -> None:
    class Dummy:
        should_exit = False

    client.app.state.uvicorn_server = Dummy()
    response = client.post("/api/shutdown")
    assert response.status_code == 200
    assert response.json()["status"] == "shutting_down"
    assert client.app.state.uvicorn_server.should_exit is True
