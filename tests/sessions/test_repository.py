"""Session, user-settings, and receipt persistence (spec 4.2, 4.3, 4.4)."""

from __future__ import annotations

from datetime import UTC, datetime

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


def _receipt(user_id: int, created_at: datetime) -> Receipt:
    return Receipt(
        telegram_user_id=user_id,
        country_code="US",
        currency="USD",
        total=10.0,
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
