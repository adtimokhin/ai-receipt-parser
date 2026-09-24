"""Named collection accessors and index bootstrap (spec Section 4).

Mirrors the ``blob_storage`` ``ensure_bucket`` pattern: index creation is
idempotent and safe to run on every boot.
"""

from __future__ import annotations

from pymongo import ASCENDING, IndexModel
from pymongo.asynchronous.collection import AsyncCollection

from receipt_parser_backend.db.mongodb.client import Document, get_database

# Telegram delivers each update at most a handful of times on retry; a week is
# generously longer than any realistic retry window (spec 4.5).
_PROCESSED_UPDATES_TTL_SECONDS = 7 * 24 * 60 * 60


def processed_updates_collection() -> AsyncCollection[Document]:
    """The ``processed_updates`` collection (spec 4.5)."""

    return get_database()["processed_updates"]


async def ensure_indexes() -> None:
    """Create the indexes the ingress layer depends on."""

    await processed_updates_collection().create_indexes(
        [
            IndexModel([("update_id", ASCENDING)], unique=True, name="update_id_unique"),
            IndexModel(
                [("processed_at", ASCENDING)],
                expireAfterSeconds=_PROCESSED_UPDATES_TTL_SECONDS,
                name="processed_at_ttl",
            ),
        ]
    )
