"""Routes a parsed update to a command or message handler (spec Step 0.4).

``handle_command``/``handle_message`` are placeholders: Milestone 3 replaces
their bodies with the real state machine and command behavior from spec
Sections 6-7. Tests patch these two functions directly to verify routing
without depending on behavior that doesn't exist yet.
"""

from __future__ import annotations

import structlog

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
    """Placeholder. Milestone 3 implements spec Section 6 command behavior."""

    logger.info("telegram.command_received", command=command, args=args, update_id=update.update_id)


async def handle_message(update: Update) -> None:
    """Placeholder. Milestone 3 implements spec Section 7 state-based routing."""

    logger.info("telegram.message_received", update_id=update.update_id)


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
