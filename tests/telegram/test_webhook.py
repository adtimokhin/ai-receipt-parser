"""Telegram webhook ingress: secret token, dedupe, whitelist, routing (spec Step 0)."""

from __future__ import annotations

import pytest
from starlette.testclient import TestClient

from receipt_parser_backend.config import get_settings
from receipt_parser_backend.telegram import dispatch as dispatch_mod

_SECRET = "test-webhook-secret"
_WHITELISTED_USER = 111
_SECRET_HEADER = "X-Telegram-Bot-Api-Secret-Token"


def _configure(monkeypatch: pytest.MonkeyPatch, *, whitelist: str = str(_WHITELISTED_USER)) -> None:
    monkeypatch.setenv("APP_TELEGRAM_WEBHOOK_SECRET", _SECRET)
    monkeypatch.setenv("APP_TELEGRAM_WHITELIST", whitelist)
    get_settings.cache_clear()


def _update(update_id: int, user_id: int, text: str) -> dict[str, object]:
    return {
        "update_id": update_id,
        "message": {
            "message_id": update_id,
            "date": 0,
            "chat": {"id": user_id, "type": "private"},
            "from": {"id": user_id, "is_bot": False, "first_name": "Test"},
            "text": text,
        },
    }


def test_missing_secret_header_is_rejected(
    monkeypatch: pytest.MonkeyPatch, client: TestClient
) -> None:
    _configure(monkeypatch)
    response = client.post("/telegram/webhook", json=_update(1, _WHITELISTED_USER, "/status"))
    assert response.status_code == 401


def test_wrong_secret_header_is_rejected(
    monkeypatch: pytest.MonkeyPatch, client: TestClient
) -> None:
    _configure(monkeypatch)
    response = client.post(
        "/telegram/webhook",
        json=_update(1, _WHITELISTED_USER, "/status"),
        headers={_SECRET_HEADER: "wrong"},
    )
    assert response.status_code == 401


def test_non_whitelisted_sender_is_dropped(
    monkeypatch: pytest.MonkeyPatch, client: TestClient
) -> None:
    _configure(monkeypatch, whitelist=str(_WHITELISTED_USER))
    calls = []
    monkeypatch.setattr(dispatch_mod, "handle_command", lambda *a: calls.append(a))

    response = client.post(
        "/telegram/webhook",
        json=_update(1, 999, "/status"),
        headers={_SECRET_HEADER: _SECRET},
    )

    assert response.status_code == 200
    assert calls == []


def test_duplicate_update_id_is_not_dispatched_twice(
    monkeypatch: pytest.MonkeyPatch, client: TestClient
) -> None:
    _configure(monkeypatch)
    calls: list[str] = []

    async def fake_handle_command(command: str, args: str, update: object) -> None:
        calls.append(command)

    monkeypatch.setattr(dispatch_mod, "handle_command", fake_handle_command)
    payload = _update(42, _WHITELISTED_USER, "/status")
    headers = {_SECRET_HEADER: _SECRET}

    first = client.post("/telegram/webhook", json=payload, headers=headers)
    second = client.post("/telegram/webhook", json=payload, headers=headers)

    assert first.status_code == 200
    assert second.status_code == 200
    assert calls == ["/status"]


def test_command_message_is_routed_to_command_handler(
    monkeypatch: pytest.MonkeyPatch, client: TestClient
) -> None:
    _configure(monkeypatch)
    calls: list[tuple[str, str]] = []

    async def fake_handle_command(command: str, args: str, update: object) -> None:
        calls.append((command, args))

    monkeypatch.setattr(dispatch_mod, "handle_command", fake_handle_command)

    response = client.post(
        "/telegram/webhook",
        json=_update(1, _WHITELISTED_USER, "/country FR"),
        headers={_SECRET_HEADER: _SECRET},
    )

    assert response.status_code == 200
    assert calls == [("/country", "FR")]


def test_plain_text_message_is_routed_to_message_handler(
    monkeypatch: pytest.MonkeyPatch, client: TestClient
) -> None:
    _configure(monkeypatch)
    calls: list[object] = []

    async def fake_handle_message(update: object) -> None:
        calls.append(update)

    monkeypatch.setattr(dispatch_mod, "handle_message", fake_handle_message)

    response = client.post(
        "/telegram/webhook",
        json=_update(1, _WHITELISTED_USER, "hello"),
        headers={_SECRET_HEADER: _SECRET},
    )

    assert response.status_code == 200
    assert len(calls) == 1


def test_malformed_payload_is_acknowledged_without_error(
    monkeypatch: pytest.MonkeyPatch, client: TestClient
) -> None:
    _configure(monkeypatch)
    response = client.post(
        "/telegram/webhook",
        json={"not": "a telegram update"},
        headers={_SECRET_HEADER: _SECRET},
    )
    assert response.status_code == 200
