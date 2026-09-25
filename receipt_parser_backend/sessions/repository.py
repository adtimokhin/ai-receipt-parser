"""Session, user-settings, and receipt persistence (spec 4.2, 4.3, 4.4).

One document per user in ``sessions``/``user_settings``, keyed by
``telegram_user_id`` (upserted, never a growing history). ``receipts`` is
append-only, keyed by Mongo's own ``_id``.
"""

from __future__ import annotations

from datetime import UTC, datetime

from bson import ObjectId
from pymongo.asynchronous.collection import AsyncCollection

from receipt_parser_backend.db.mongodb.client import Document, get_database
from receipt_parser_backend.receipts.models import Receipt, Session, UserSettings


def _sessions_collection() -> AsyncCollection[Document]:
    return get_database()["sessions"]


def _user_settings_collection() -> AsyncCollection[Document]:
    return get_database()["user_settings"]


def _receipts_collection() -> AsyncCollection[Document]:
    return get_database()["receipts"]


async def get_session(telegram_user_id: int) -> Session:
    """Return the user's session, or a fresh ``IDLE`` one if none is stored yet."""

    doc = await _sessions_collection().find_one({"telegram_user_id": telegram_user_id})
    if doc is None:
        return Session(telegram_user_id=telegram_user_id, updated_at=datetime.now(UTC))
    doc.pop("_id", None)
    return Session.model_validate(doc)


async def save_session(session: Session) -> None:
    """Upsert ``session``, keyed by ``telegram_user_id``."""

    session.updated_at = datetime.now(UTC)
    await _sessions_collection().replace_one(
        {"telegram_user_id": session.telegram_user_id}, session.model_dump(), upsert=True
    )


async def get_user_settings(telegram_user_id: int) -> UserSettings | None:
    """Return the user's settings, or ``None`` if they haven't set any yet."""

    doc = await _user_settings_collection().find_one({"telegram_user_id": telegram_user_id})
    if doc is None:
        return None
    doc.pop("_id", None)
    return UserSettings.model_validate(doc)


async def save_user_settings(settings: UserSettings) -> None:
    """Upsert ``settings``, keyed by ``telegram_user_id``."""

    settings.updated_at = datetime.now(UTC)
    await _user_settings_collection().replace_one(
        {"telegram_user_id": settings.telegram_user_id}, settings.model_dump(), upsert=True
    )


async def insert_receipt(receipt: Receipt) -> str:
    """Insert ``receipt`` and return its new Mongo id as a string."""

    result = await _receipts_collection().insert_one(receipt.model_dump(exclude={"id"}))
    return str(result.inserted_id)


async def get_last_receipt(telegram_user_id: int) -> Receipt | None:
    """Return the most recently saved receipt for ``telegram_user_id``, if any."""

    doc = await _receipts_collection().find_one(
        {"telegram_user_id": telegram_user_id}, sort=[("created_at", -1)]
    )
    if doc is None:
        return None
    doc["_id"] = str(doc["_id"])
    return Receipt.model_validate(doc)


async def delete_receipt(receipt_id: str) -> None:
    """Delete a receipt by its Mongo id (spec ``/undo``)."""

    await _receipts_collection().delete_one({"_id": ObjectId(receipt_id)})
