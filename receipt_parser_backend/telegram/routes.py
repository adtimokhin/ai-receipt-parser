"""Telegram webhook ingress (spec Section 3, Step 0).

Order matches the spec exactly: secret token, then dedupe, then whitelist,
then routing. The endpoint always acknowledges with 200 once the secret token
has checked out, per Step 0.5 ("acknowledge the webhook quickly") - including
for payloads we can't parse or senders we drop, since those aren't Telegram's
problem to retry.
"""

from __future__ import annotations

import secrets

import structlog
from fastapi import APIRouter, Request, Response, status
from pydantic import ValidationError

from receipt_parser_backend.config import get_settings
from receipt_parser_backend.telegram.dedupe import is_duplicate_update
from receipt_parser_backend.telegram.dispatch import dispatch
from receipt_parser_backend.telegram.models import Update

router = APIRouter(prefix="/telegram", tags=["telegram"])
logger = structlog.get_logger(__name__)

_SECRET_HEADER = "x-telegram-bot-api-secret-token"


@router.post("/webhook")
async def webhook(request: Request, response: Response) -> dict[str, bool]:
    settings = get_settings()

    secret = request.headers.get(_SECRET_HEADER)
    if secret is None or not secrets.compare_digest(secret, settings.telegram_webhook_secret):
        response.status_code = status.HTTP_401_UNAUTHORIZED
        return {"ok": False}

    try:
        payload = await request.json()
        update = Update.model_validate(payload)
    except (ValueError, ValidationError) as exc:
        logger.warning("telegram.webhook_invalid_payload", error=str(exc))
        return {"ok": True}

    if await is_duplicate_update(update.update_id):
        return {"ok": True}

    sender = update.message.from_user if update.message else None
    if sender is None or sender.id not in settings.telegram_whitelist_ids:
        logger.info(
            "telegram.update_dropped",
            reason="not_whitelisted",
            update_id=update.update_id,
        )
        return {"ok": True}

    await dispatch(update)
    return {"ok": True}
