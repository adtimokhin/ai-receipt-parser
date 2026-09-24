"""Command vs. message routing (spec Step 0.4)."""

from __future__ import annotations

import pytest

from receipt_parser_backend.telegram import dispatch as dispatch_mod
from receipt_parser_backend.telegram.dispatch import dispatch, extract_command
from receipt_parser_backend.telegram.models import Chat, Message, Update

_CHAT = Chat(id=1, type="private")


def _message(text: str | None = None, **kwargs: object) -> Message:
    return Message(message_id=1, date=0, chat=_CHAT, text=text, **kwargs)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("/country FR", ("/country", "FR")),
        ("/country", ("/country", "")),
        ("/country@MyBot FR", ("/country", "FR")),
        ("/country@MyBot", ("/country", "")),
        ("/status   ", ("/status", "")),
        ("hello there", None),
        ("", None),
        (None, None),
    ],
)
def test_extract_command(text: str | None, expected: tuple[str, str] | None) -> None:
    assert extract_command(_message(text)) == expected


async def test_dispatch_routes_command(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, str]] = []

    async def fake_handle_command(command: str, args: str, update: Update) -> None:
        calls.append((command, args))

    monkeypatch.setattr(dispatch_mod, "handle_command", fake_handle_command)
    update = Update(update_id=1, message=_message("/country FR"))

    await dispatch(update)

    assert calls == [("/country", "FR")]


async def test_dispatch_routes_plain_text_to_message_handler(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[Update] = []

    async def fake_handle_message(update: Update) -> None:
        calls.append(update)

    monkeypatch.setattr(dispatch_mod, "handle_message", fake_handle_message)
    update = Update(update_id=2, message=_message("hello there"))

    await dispatch(update)

    assert calls == [update]


async def test_dispatch_routes_document_to_message_handler(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[Update] = []

    async def fake_handle_message(update: Update) -> None:
        calls.append(update)

    monkeypatch.setattr(dispatch_mod, "handle_message", fake_handle_message)
    update = Update(
        update_id=3,
        message=_message(document={"file_id": "f1", "file_unique_id": "u1"}),
    )

    await dispatch(update)

    assert calls == [update]


async def test_dispatch_ignores_updates_without_a_message(monkeypatch: pytest.MonkeyPatch) -> None:
    command_calls: list[object] = []
    message_calls: list[object] = []

    async def fake_handle_command(command: str, args: str, update: Update) -> None:
        command_calls.append((command, args, update))

    async def fake_handle_message(update: Update) -> None:
        message_calls.append(update)

    monkeypatch.setattr(dispatch_mod, "handle_command", fake_handle_command)
    monkeypatch.setattr(dispatch_mod, "handle_message", fake_handle_message)

    await dispatch(Update(update_id=4, message=None))

    assert command_calls == []
    assert message_calls == []
