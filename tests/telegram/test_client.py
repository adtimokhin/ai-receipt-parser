"""Telegram Bot API client: sending messages and downloading files (spec Step 1.4)."""

from __future__ import annotations

import json

import pytest

from receipt_parser_backend.telegram.client import download_file
from tests.conftest import FAKE_TELEGRAM_FILE_CONTENT


async def test_download_file_returns_the_files_bytes(
    telegram_client: list[dict[str, object]],
) -> None:
    content = await download_file("some-file-id")
    assert content == FAKE_TELEGRAM_FILE_CONTENT


async def test_send_message_posts_chat_id_and_text(
    telegram_client: list[dict[str, object]],
) -> None:
    from receipt_parser_backend.telegram.client import send_message

    await send_message(42, "hello")

    assert telegram_client == [{"chat_id": 42, "text": "hello"}]


async def test_download_file_raises_on_http_error(
    monkeypatch: pytest.MonkeyPatch, telegram_client: list[dict[str, object]]
) -> None:
    import httpx

    from receipt_parser_backend.telegram import client as client_mod

    def _handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"ok": False})

    client_mod._client = httpx.AsyncClient(
        base_url="https://api.telegram.org/bottest-token", transport=httpx.MockTransport(_handler)
    )

    with pytest.raises(httpx.HTTPStatusError):
        await download_file("some-file-id")


async def test_set_my_commands_sends_the_full_command_list(
    telegram_client: list[dict[str, object]],
) -> None:
    import httpx

    from receipt_parser_backend.telegram import client as client_mod
    from receipt_parser_backend.telegram.client import BOT_COMMANDS, set_my_commands

    captured: list[httpx.Request] = []

    def _handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json={"ok": True, "result": True})

    client_mod._client = httpx.AsyncClient(
        base_url="https://api.telegram.org/bottest-token", transport=httpx.MockTransport(_handler)
    )

    await set_my_commands()

    assert len(captured) == 1
    assert captured[0].url.path.endswith("/setMyCommands")
    body = json.loads(captured[0].content)
    assert body["commands"] == [
        {"command": name, "description": desc} for name, desc in BOT_COMMANDS
    ]


async def test_set_my_commands_raises_on_http_error(
    telegram_client: list[dict[str, object]],
) -> None:
    import httpx

    from receipt_parser_backend.telegram import client as client_mod
    from receipt_parser_backend.telegram.client import set_my_commands

    def _handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"ok": False, "description": "bad request"})

    client_mod._client = httpx.AsyncClient(
        base_url="https://api.telegram.org/bottest-token", transport=httpx.MockTransport(_handler)
    )

    with pytest.raises(httpx.HTTPStatusError):
        await set_my_commands()


async def test_send_document_posts_the_file_and_caption(
    telegram_client: list[dict[str, object]],
) -> None:
    import httpx

    from receipt_parser_backend.telegram import client as client_mod
    from receipt_parser_backend.telegram.client import send_document

    captured: list[httpx.Request] = []

    def _handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json={"ok": True, "result": {}})

    client_mod._client = httpx.AsyncClient(
        base_url="https://api.telegram.org/bottest-token", transport=httpx.MockTransport(_handler)
    )

    await send_document(42, "report.pdf", b"%PDF-fake-bytes", caption="Here is your report")

    assert len(captured) == 1
    request = captured[0]
    assert request.url.path.endswith("/sendDocument")
    body = request.content
    assert b'name="chat_id"' in body
    assert b"42" in body
    assert b'filename="report.pdf"' in body
    assert b"%PDF-fake-bytes" in body
    assert b"Here is your report" in body


async def test_send_document_without_a_caption_omits_it(
    telegram_client: list[dict[str, object]],
) -> None:
    import httpx

    from receipt_parser_backend.telegram import client as client_mod
    from receipt_parser_backend.telegram.client import send_document

    captured: list[httpx.Request] = []

    def _handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json={"ok": True, "result": {}})

    client_mod._client = httpx.AsyncClient(
        base_url="https://api.telegram.org/bottest-token", transport=httpx.MockTransport(_handler)
    )

    await send_document(42, "report.pdf", b"%PDF-fake-bytes")

    assert b'name="caption"' not in captured[0].content


async def test_send_document_raises_on_http_error(
    telegram_client: list[dict[str, object]],
) -> None:
    import httpx

    from receipt_parser_backend.telegram import client as client_mod
    from receipt_parser_backend.telegram.client import send_document

    def _handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"ok": False, "description": "bad request"})

    client_mod._client = httpx.AsyncClient(
        base_url="https://api.telegram.org/bottest-token", transport=httpx.MockTransport(_handler)
    )

    with pytest.raises(httpx.HTTPStatusError):
        await send_document(42, "report.pdf", b"%PDF-fake-bytes")
