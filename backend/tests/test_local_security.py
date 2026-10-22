"""Unit tests for localhost control guards."""

from __future__ import annotations

import pytest

from gheymatyar.local_security import (
    is_loopback_host,
    is_loopback_origin,
    token_equals,
)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("127.0.0.1", True),
        ("127.0.0.1:8765", True),
        ("localhost", True),
        ("localhost:8765", True),
        ("[::1]", True),
        ("[::1]:8765", True),
        ("testserver", True),
        ("evil.example", False),
        ("192.168.1.1", False),
        (None, False),
        ("", False),
    ],
)
def test_is_loopback_host(value: str | None, expected: bool) -> None:
    assert is_loopback_host(value) is expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, True),
        ("http://127.0.0.1:8765", True),
        ("http://localhost", True),
        ("https://evil.example", False),
        ("http://192.168.0.1", False),
    ],
)
def test_is_loopback_origin(value: str | None, expected: bool) -> None:
    assert is_loopback_origin(value) is expected


def test_token_equals() -> None:
    assert token_equals("abc", "abc") is True
    assert token_equals("abc", "abd") is False
    assert token_equals("abc", "ab") is False
