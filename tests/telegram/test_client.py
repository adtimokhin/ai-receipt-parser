"""Telegram Bot API client: sending messages and downloading files (spec Step 1.4)."""

from __future__ import annotations

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
