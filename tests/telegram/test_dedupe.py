"""Webhook update_id dedupe (spec Step 0.2)."""

from __future__ import annotations

from receipt_parser_backend.telegram.dedupe import is_duplicate_update
from tests.telegram.conftest import FakeProcessedUpdatesCollection


async def test_first_delivery_is_not_a_duplicate(
    fake_processed_updates: FakeProcessedUpdatesCollection,
) -> None:
    assert await is_duplicate_update(1) is False


async def test_redelivery_of_the_same_update_id_is_a_duplicate(
    fake_processed_updates: FakeProcessedUpdatesCollection,
) -> None:
    assert await is_duplicate_update(1) is False
    assert await is_duplicate_update(1) is True


async def test_different_update_ids_are_independent(
    fake_processed_updates: FakeProcessedUpdatesCollection,
) -> None:
    assert await is_duplicate_update(1) is False
    assert await is_duplicate_update(2) is False
