"""Async Telegram Bot API client, bound to the FastAPI lifespan."""

from __future__ import annotations

import httpx

from receipt_parser_backend.config import get_settings

_client: httpx.AsyncClient | None = None


def init_client() -> httpx.AsyncClient:
    """Build the client from settings. Idempotent within a process."""

    global _client

    settings = get_settings()
    _client = httpx.AsyncClient(
        base_url=f"https://api.telegram.org/bot{settings.telegram_bot_token}",
        timeout=10.0,
    )
    return _client


def get_client() -> httpx.AsyncClient:
    """Return the process-wide client, or raise if the lifespan has not run."""

    if _client is None:
        raise RuntimeError(
            "Telegram client is not initialised; is the application lifespan running?"
        )
    return _client


async def close_client() -> None:
    """Close the client and clear the holder."""

    global _client

    if _client is not None:
        await _client.aclose()
    _client = None


async def send_message(chat_id: int, text: str) -> None:
    """Send ``text`` to ``chat_id`` via ``sendMessage``."""

    response = await get_client().post("/sendMessage", json={"chat_id": chat_id, "text": text})
    response.raise_for_status()


async def send_document(
    chat_id: int,
    filename: str,
    content: bytes,
    caption: str | None = None,
    content_type: str = "application/pdf",
) -> None:
    """Send ``content`` as a file attachment via ``sendDocument`` (e.g. a /report PDF or .xlsx)."""

    data = {"chat_id": str(chat_id)}
    if caption:
        data["caption"] = caption
    files = {"document": (filename, content, content_type)}
    response = await get_client().post("/sendDocument", data=data, files=files)
    response.raise_for_status()


async def download_file(file_id: str) -> bytes:
    """Download a file's bytes via ``getFile`` (spec Step 1.4).

    Telegram's hosted Bot API caps downloads at 20 MB - the same cap Step 1.3
    already enforces on ``file_size`` before this is ever called.
    """

    settings = get_settings()
    client = get_client()

    response = await client.get("/getFile", params={"file_id": file_id})
    response.raise_for_status()
    file_path = response.json()["result"]["file_path"]

    file_url = f"https://api.telegram.org/file/bot{settings.telegram_bot_token}/{file_path}"
    file_response = await client.get(file_url)
    file_response.raise_for_status()
    return file_response.content


# The "/" menu Telegram clients show next to the message box. Order matches
# spec Section 6's command table; descriptions are Telegram UI copy, kept
# separate from messages.HELP_TEXT's fuller sentences.
BOT_COMMANDS: list[tuple[str, str]] = [
    ("start", "Greeting and how-to"),
    ("help", "List every command"),
    ("country", "Show or set your country"),
    ("status", "Show the current state and active question"),
    ("show", "Re-display the current draft"),
    ("confirm", "Save the current draft"),
    ("cancel", "Stop processing or discard the draft"),
    ("last", "Show your most recently saved receipt"),
    ("undo", "Delete your most recently saved receipt"),
    ("report", "Get a PDF + Excel report of categorized receipts in a date range"),
]


async def set_my_commands() -> None:
    """Populate Telegram's native command menu. Idempotent - safe on every boot."""

    commands = [{"command": name, "description": description} for name, description in BOT_COMMANDS]
    response = await get_client().post("/setMyCommands", json={"commands": commands})
    response.raise_for_status()
