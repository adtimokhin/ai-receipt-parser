"""Routes a parsed update to a command or message handler (spec Step 0.4).

Delegates to :data:`receipt_parser_backend.pipeline.engine.default_pipeline`
for everything past classification - this module only ever deals with
Telegram's own types. Tests patch ``handle_command``/``handle_message``
directly to verify routing independently of the pipeline's behavior.
"""

from __future__ import annotations

import structlog

from receipt_parser_backend.pipeline.engine import default_pipeline
from receipt_parser_backend.telegram.models import Message, Update

logger = structlog.get_logger(__name__)


def extract_command(message: Message) -> tuple[str, str] | None:
    """Return ``(command, args)`` if ``message`` is a slash command, else ``None``.

    Strips a ``@BotName`` mention suffix (e.g. ``/country@MyBot FR``), which
    Telegram clients add in group chats and sometimes in private chats too.
    """

    text = message.text
    if not text or not text.startswith("/"):
        return None
    head, _, rest = text.partition(" ")
    command = head.split("@", 1)[0]
    return command, rest.strip()


async def handle_command(command: str, args: str, update: Update) -> None:
    """Run a slash command through the state machine (spec Section 6)."""

    user_id = _sender_id(update)
    await default_pipeline.handle_command(user_id, command, args)


async def handle_message(update: Update) -> None:
    """Classify a non-command message and route it (spec Section 7 table)."""

    message = update.message
    assert message is not None
    user_id = _sender_id(update)

    if message.document is not None:
        await default_pipeline.handle_document(
            user_id,
            message.document.file_id,
            message.document.mime_type or "",
            message.document.file_size or 0,
        )
    elif message.photo:
        await default_pipeline.handle_compressed_photo(user_id)
    elif message.text is not None:
        await default_pipeline.handle_text(user_id, message.text)
    else:
        logger.info("telegram.message_ignored", update_id=update.update_id)


def _sender_id(update: Update) -> int:
    message = update.message
    assert message is not None
    assert (
        message.from_user is not None
    )  # the webhook already dropped unwhitelisted/senderless updates
    return message.from_user.id


async def dispatch(update: Update) -> None:
    """Classify ``update.message`` and call the matching handler.

    Update types other than a plain message (edited messages, callback
    queries, channel posts, ...) are out of v1's scope and are ignored.
    """

    message = update.message
    if message is None:
        return

    command = extract_command(message)
    if command is not None:
        name, args = command
        await handle_command(name, args, update)
    else:
        await handle_message(update)
