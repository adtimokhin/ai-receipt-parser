"""Webhook ``update_id`` dedupe (spec Step 0.2, 4.5)."""

from __future__ import annotations

from datetime import UTC, datetime

from pymongo.errors import DuplicateKeyError

from receipt_parser_backend.db.mongodb.collections import processed_updates_collection


async def is_duplicate_update(update_id: int) -> bool:
    """Record ``update_id`` as processed. Return ``True`` if already recorded."""

    try:
        await processed_updates_collection().insert_one(
            {"update_id": update_id, "processed_at": datetime.now(UTC)}
        )
    except DuplicateKeyError:
        return True
    return False
