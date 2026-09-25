"""Session, user-settings, and receipt persistence (spec 4.2, 4.3, 4.4)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from receipt_parser_backend.receipts.models import (
    Draft,
    Item,
    Receipt,
    ReceiptFiles,
    Session,
    SessionState,
    UserSettings,
)
from receipt_parser_backend.sessions import repository


async def test_get_session_returns_fresh_idle_session_when_none_stored(
    fake_repository_db: object,
) -> None:
    session = await repository.get_session(1)
    assert session.state == SessionState.IDLE
    assert session.telegram_user_id == 1


async def test_save_and_get_session_roundtrips(fake_repository_db: object) -> None:
    session = Session(
        telegram_user_id=1,
        state=SessionState.AWAITING_ANSWERS,
        country_code="US",
        draft=Draft(currency="USD", items=[Item(name="a", price=1.5)]),
        question_queue=["missing_date"],
        current_question="missing_date",
        updated_at=datetime.now(UTC),
    )
    await repository.save_session(session)

    fetched = await repository.get_session(1)

    assert fetched.state == SessionState.AWAITING_ANSWERS
    assert fetched.country_code == "US"
    assert fetched.draft is not None
    assert fetched.draft.items == [Item(name="a", price=1.5)]
    assert fetched.current_question == "missing_date"


async def test_save_session_upserts_rather_than_duplicating(fake_repository_db: object) -> None:
    first = Session(telegram_user_id=1, updated_at=datetime.now(UTC))
    await repository.save_session(first)
    second = Session(
        telegram_user_id=1, state=SessionState.PROCESSING, updated_at=datetime.now(UTC)
    )
    await repository.save_session(second)

    fetched = await repository.get_session(1)

    assert fetched.state == SessionState.PROCESSING


async def test_get_user_settings_returns_none_when_unset(fake_repository_db: object) -> None:
    assert await repository.get_user_settings(1) is None


async def test_save_and_get_user_settings_roundtrips(fake_repository_db: object) -> None:
    await repository.save_user_settings(
        UserSettings(telegram_user_id=1, country_code="FR", updated_at=datetime.now(UTC))
    )
    settings = await repository.get_user_settings(1)
    assert settings is not None
    assert settings.country_code == "FR"


def _receipt(
    user_id: int,
    created_at: datetime,
    *,
    date: str | None = None,
    category: Literal["room", "board"] | None = None,
    merchant_name: str | None = None,
) -> Receipt:
    return Receipt(
        telegram_user_id=user_id,
        country_code="US",
        merchant_name=merchant_name,
        currency="USD",
        date=date,
        total=10.0,
        category=category,
        files=ReceiptFiles(original_r2_key=""),
        created_at=created_at,
    )


async def test_get_last_receipt_returns_none_when_empty(fake_repository_db: object) -> None:
    assert await repository.get_last_receipt(1) is None


async def test_get_last_receipt_returns_the_most_recent(fake_repository_db: object) -> None:
    older = _receipt(1, datetime(2026, 1, 1, tzinfo=UTC))
    newer = _receipt(1, datetime(2026, 6, 1, tzinfo=UTC))
    await repository.insert_receipt(older)
    await repository.insert_receipt(newer)

    fetched = await repository.get_last_receipt(1)

    assert fetched is not None
    assert fetched.created_at == newer.created_at


async def test_get_last_receipt_is_scoped_to_the_user(fake_repository_db: object) -> None:
    await repository.insert_receipt(_receipt(1, datetime.now(UTC)))
    assert await repository.get_last_receipt(2) is None


async def test_delete_receipt_removes_it(fake_repository_db: object) -> None:
    receipt_id = await repository.insert_receipt(_receipt(1, datetime.now(UTC)))
    await repository.delete_receipt(receipt_id)
    assert await repository.get_last_receipt(1) is None


# --- get_categorized_receipts_in_range (spec-adjacent, /report) --------------


async def test_range_query_excludes_uncategorized_receipts(fake_repository_db: object) -> None:
    await repository.insert_receipt(
        _receipt(1, datetime.now(UTC), date="2026-01-15", category=None)
    )
    results = await repository.get_categorized_receipts_in_range(1, "2026-01-01", "2026-01-31")
    assert results == []


async def test_range_query_includes_room_and_board(fake_repository_db: object) -> None:
    await repository.insert_receipt(
        _receipt(1, datetime.now(UTC), date="2026-01-05", category="room", merchant_name="Landlord")
    )
    await repository.insert_receipt(
        _receipt(1, datetime.now(UTC), date="2026-01-10", category="board", merchant_name="Grocer")
    )
    results = await repository.get_categorized_receipts_in_range(1, "2026-01-01", "2026-01-31")
    assert [r.merchant_name for r in results] == ["Landlord", "Grocer"]


async def test_range_query_excludes_dates_outside_the_range(fake_repository_db: object) -> None:
    await repository.insert_receipt(
        _receipt(1, datetime.now(UTC), date="2025-12-31", category="room")
    )
    await repository.insert_receipt(
        _receipt(1, datetime.now(UTC), date="2026-02-01", category="room")
    )
    results = await repository.get_categorized_receipts_in_range(1, "2026-01-01", "2026-01-31")
    assert results == []


async def test_range_query_bounds_are_inclusive(fake_repository_db: object) -> None:
    await repository.insert_receipt(
        _receipt(1, datetime.now(UTC), date="2026-01-01", category="room")
    )
    await repository.insert_receipt(
        _receipt(1, datetime.now(UTC), date="2026-01-31", category="board")
    )
    results = await repository.get_categorized_receipts_in_range(1, "2026-01-01", "2026-01-31")
    assert len(results) == 2


async def test_range_query_is_scoped_to_the_user(fake_repository_db: object) -> None:
    await repository.insert_receipt(
        _receipt(1, datetime.now(UTC), date="2026-01-15", category="room")
    )
    results = await repository.get_categorized_receipts_in_range(2, "2026-01-01", "2026-01-31")
    assert results == []


async def test_range_query_sorts_chronologically(fake_repository_db: object) -> None:
    await repository.insert_receipt(
        _receipt(1, datetime.now(UTC), date="2026-01-20", category="room", merchant_name="Second")
    )
    await repository.insert_receipt(
        _receipt(1, datetime.now(UTC), date="2026-01-05", category="board", merchant_name="First")
    )
    results = await repository.get_categorized_receipts_in_range(1, "2026-01-01", "2026-01-31")
    assert [r.merchant_name for r in results] == ["First", "Second"]
