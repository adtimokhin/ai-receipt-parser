"""Shared fixtures for telegram ingress tests."""

from __future__ import annotations

from typing import Any

import pytest
from pymongo.errors import DuplicateKeyError

from receipt_parser_backend.telegram import dedupe as dedupe_mod


class FakeProcessedUpdatesCollection:
    """Mimics the unique-indexed ``processed_updates`` collection (spec 4.5)."""

    def __init__(self) -> None:
        self._seen: set[int] = set()

    async def insert_one(self, document: dict[str, Any]) -> None:
        update_id = document["update_id"]
        if update_id in self._seen:
            raise DuplicateKeyError("update_id already recorded")
        self._seen.add(update_id)


@pytest.fixture(autouse=True)
def fake_processed_updates(monkeypatch: pytest.MonkeyPatch) -> FakeProcessedUpdatesCollection:
    """Replace the real Mongo collection so dedupe tests run with no database.

    The autouse ``mongodb_db`` fixture (top-level conftest) stubs the client
    with an ``AsyncMock``, but indexing into it returns a plain (non-async)
    ``MagicMock``, which can't be awaited - fine for the ``ping`` health check,
    not for ``insert_one``. This gives every telegram test a working fake.
    """

    fake = FakeProcessedUpdatesCollection()
    monkeypatch.setattr(dedupe_mod, "processed_updates_collection", lambda: fake)
    return fake
