"""The state machine: Section 6 commands and Section 7 transitions."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest

from receipt_parser_backend.ai.extraction import RawExtraction, RawExtractionItem
from receipt_parser_backend.ai.fakes import FakeExtractor, FakeInterpreter
from receipt_parser_backend.ai.interpreter import InterpreterOutput, SetOp
from receipt_parser_backend.pipeline import messages
from receipt_parser_backend.pipeline.engine import ReceiptPipeline
from receipt_parser_backend.receipts.models import (
    Draft,
    Item,
    Receipt,
    ReceiptFiles,
    Session,
    SessionState,
    TotalCheck,
    UserSettings,
)
from receipt_parser_backend.sessions import repository

USER = 111


@pytest.fixture
def extractor() -> FakeExtractor:
    return FakeExtractor()


@pytest.fixture
def interpreter() -> FakeInterpreter:
    return FakeInterpreter()


@pytest.fixture
def pipeline(
    fake_repository_db: object, extractor: FakeExtractor, interpreter: FakeInterpreter
) -> ReceiptPipeline:
    return ReceiptPipeline(extractor=extractor, interpreter=interpreter)


def _last_text(sent: list[dict[str, object]]) -> str:
    return str(sent[-1]["text"])


async def _set_country(code: str = "US") -> None:
    await repository.save_user_settings(
        UserSettings(telegram_user_id=USER, country_code=code, updated_at=datetime.now(UTC))
    )


async def _put_session(**kwargs: object) -> Session:
    session = Session(telegram_user_id=USER, updated_at=datetime.now(UTC), **kwargs)
    await repository.save_session(session)
    return session


# --- commands available in any state ----------------------------------------


async def test_start_replies_with_greeting(
    pipeline: ReceiptPipeline, telegram_client: list[dict[str, object]]
) -> None:
    await pipeline.handle_command(USER, "/start", "")
    assert "receipt" in _last_text(telegram_client).lower()


async def test_help_lists_commands(
    pipeline: ReceiptPipeline, telegram_client: list[dict[str, object]]
) -> None:
    await pipeline.handle_command(USER, "/help", "")
    assert "/confirm" in _last_text(telegram_client)


async def test_unknown_command_gets_a_help_pointer(
    pipeline: ReceiptPipeline, telegram_client: list[dict[str, object]]
) -> None:
    await pipeline.handle_command(USER, "/nope", "")
    assert _last_text(telegram_client) == messages.UNKNOWN_COMMAND


# --- /country ----------------------------------------------------------------


async def test_country_show_reports_not_set_by_default(
    pipeline: ReceiptPipeline, telegram_client: list[dict[str, object]]
) -> None:
    await pipeline.handle_command(USER, "/country", "")
    assert "not set" in _last_text(telegram_client)


async def test_country_show_reports_the_active_country(
    pipeline: ReceiptPipeline, telegram_client: list[dict[str, object]]
) -> None:
    await _set_country("FR")
    await pipeline.handle_command(USER, "/country", "")
    assert "FR" in _last_text(telegram_client)


async def test_country_set_while_idle_succeeds(
    pipeline: ReceiptPipeline, telegram_client: list[dict[str, object]]
) -> None:
    await pipeline.handle_command(USER, "/country", "US")
    settings = await repository.get_user_settings(USER)
    assert settings is not None
    assert settings.country_code == "US"
    assert "US" in _last_text(telegram_client)


async def test_country_set_with_unsupported_code_is_rejected(
    pipeline: ReceiptPipeline, telegram_client: list[dict[str, object]]
) -> None:
    await pipeline.handle_command(USER, "/country", "DE")
    assert await repository.get_user_settings(USER) is None
    assert "supported" in _last_text(telegram_client).lower()


async def test_country_set_outside_idle_is_rejected(
    pipeline: ReceiptPipeline, telegram_client: list[dict[str, object]]
) -> None:
    await _put_session(state=SessionState.PROCESSING)
    await pipeline.handle_command(USER, "/country", "US")
    assert await repository.get_user_settings(USER) is None


# --- /status -------------------------------------------------------------------


async def test_status_reports_idle_with_no_question(
    pipeline: ReceiptPipeline, telegram_client: list[dict[str, object]]
) -> None:
    await pipeline.handle_command(USER, "/status", "")
    text = _last_text(telegram_client)
    assert "IDLE" in text
    assert "question" not in text.lower()


async def test_status_reports_the_active_question(
    pipeline: ReceiptPipeline, telegram_client: list[dict[str, object]]
) -> None:
    await _put_session(state=SessionState.AWAITING_ANSWERS, current_question="missing_date")
    await pipeline.handle_command(USER, "/status", "")
    assert "missing_date" in _last_text(telegram_client)


# --- /show ---------------------------------------------------------------------


async def test_show_is_rejected_while_idle(
    pipeline: ReceiptPipeline, telegram_client: list[dict[str, object]]
) -> None:
    await pipeline.handle_command(USER, "/show", "")
    assert "only works" in _last_text(telegram_client)


async def test_show_is_rejected_while_processing(
    pipeline: ReceiptPipeline, telegram_client: list[dict[str, object]]
) -> None:
    await _put_session(state=SessionState.PROCESSING)
    await pipeline.handle_command(USER, "/show", "")
    assert "only works" in _last_text(telegram_client)


async def test_show_renders_the_draft_and_active_question(
    pipeline: ReceiptPipeline, telegram_client: list[dict[str, object]]
) -> None:
    from receipt_parser_backend.receipts.models import Draft

    draft = Draft(currency="USD", merchant_name="Fake Mart")
    await _put_session(
        state=SessionState.AWAITING_ANSWERS, draft=draft, current_question="missing_date"
    )
    await pipeline.handle_command(USER, "/show", "")
    text = _last_text(telegram_client)
    assert "Fake Mart" in text
    assert "date" in text.lower()


async def test_show_renders_the_confirmation_prompt(
    pipeline: ReceiptPipeline, telegram_client: list[dict[str, object]]
) -> None:
    from receipt_parser_backend.receipts.models import Draft

    draft = Draft(currency="USD", merchant_name="Fake Mart", date="2026-01-15", total=10.0)
    await _put_session(state=SessionState.AWAITING_CONFIRMATION, draft=draft)
    await pipeline.handle_command(USER, "/show", "")
    assert "/confirm" in _last_text(telegram_client)


# --- /confirm --------------------------------------------------------------------


async def test_confirm_is_rejected_outside_awaiting_confirmation(
    pipeline: ReceiptPipeline, telegram_client: list[dict[str, object]]
) -> None:
    await pipeline.handle_command(USER, "/confirm", "")
    assert "only works" in _last_text(telegram_client)
    assert await repository.get_last_receipt(USER) is None


async def test_confirm_persists_the_receipt_and_returns_to_idle(
    pipeline: ReceiptPipeline, telegram_client: list[dict[str, object]]
) -> None:
    from receipt_parser_backend.receipts.models import Draft

    draft = Draft(currency="USD", merchant_name="Fake Mart", date="2026-01-15", total=10.0)
    await _put_session(state=SessionState.AWAITING_CONFIRMATION, country_code="US", draft=draft)

    await pipeline.handle_command(USER, "/confirm", "")

    assert _last_text(telegram_client) == messages.SAVED
    session = await repository.get_session(USER)
    assert session.state == SessionState.IDLE
    assert session.draft is None
    receipt = await repository.get_last_receipt(USER)
    assert receipt is not None
    assert receipt.merchant_name == "Fake Mart"


# --- /cancel ---------------------------------------------------------------------


async def test_cancel_is_rejected_while_idle(
    pipeline: ReceiptPipeline, telegram_client: list[dict[str, object]]
) -> None:
    await pipeline.handle_command(USER, "/cancel", "")
    assert "only works" in _last_text(telegram_client)


@pytest.mark.parametrize(
    "state",
    [SessionState.PROCESSING, SessionState.AWAITING_ANSWERS, SessionState.AWAITING_CONFIRMATION],
)
async def test_cancel_returns_to_idle_from_any_busy_state(
    pipeline: ReceiptPipeline, telegram_client: list[dict[str, object]], state: SessionState
) -> None:
    await _put_session(state=state, extraction_job_id="job-1")
    await pipeline.handle_command(USER, "/cancel", "")
    session = await repository.get_session(USER)
    assert session.state == SessionState.IDLE
    assert session.cancelled is True
    assert _last_text(telegram_client) == messages.CANCELLED


# --- /last -----------------------------------------------------------------------


async def test_last_reports_no_receipts_yet(
    pipeline: ReceiptPipeline, telegram_client: list[dict[str, object]]
) -> None:
    await pipeline.handle_command(USER, "/last", "")
    assert _last_text(telegram_client) == messages.NO_RECEIPTS_YET


async def test_last_shows_the_most_recent_receipt(
    pipeline: ReceiptPipeline, telegram_client: list[dict[str, object]]
) -> None:
    await repository.insert_receipt(
        Receipt(
            telegram_user_id=USER,
            country_code="US",
            merchant_name="Fake Mart",
            currency="USD",
            total=10.0,
            files=ReceiptFiles(original_r2_key=""),
            created_at=datetime.now(UTC),
        )
    )
    await pipeline.handle_command(USER, "/last", "")
    assert "Fake Mart" in _last_text(telegram_client)


async def test_last_is_rejected_outside_idle(
    pipeline: ReceiptPipeline, telegram_client: list[dict[str, object]]
) -> None:
    await _put_session(state=SessionState.PROCESSING)
    await pipeline.handle_command(USER, "/last", "")
    assert "only works" in _last_text(telegram_client)


# --- /undo -----------------------------------------------------------------------


async def test_undo_reports_no_receipts_yet(
    pipeline: ReceiptPipeline, telegram_client: list[dict[str, object]]
) -> None:
    await pipeline.handle_command(USER, "/undo", "")
    assert _last_text(telegram_client) == messages.NO_RECEIPTS_YET


async def test_undo_asks_for_confirmation_first(
    pipeline: ReceiptPipeline, telegram_client: list[dict[str, object]]
) -> None:
    await repository.insert_receipt(
        Receipt(
            telegram_user_id=USER,
            country_code="US",
            currency="USD",
            total=10.0,
            files=ReceiptFiles(original_r2_key=""),
            created_at=datetime.now(UTC),
        )
    )
    await pipeline.handle_command(USER, "/undo", "")
    assert "again to confirm" in _last_text(telegram_client)
    assert (await repository.get_last_receipt(USER)) is not None  # not deleted yet


async def test_undo_confirmed_deletes_the_receipt(
    pipeline: ReceiptPipeline, telegram_client: list[dict[str, object]]
) -> None:
    await repository.insert_receipt(
        Receipt(
            telegram_user_id=USER,
            country_code="US",
            currency="USD",
            total=10.0,
            files=ReceiptFiles(original_r2_key=""),
            created_at=datetime.now(UTC),
        )
    )
    await pipeline.handle_command(USER, "/undo", "")
    await pipeline.handle_command(USER, "/undo", "")
    assert _last_text(telegram_client) == messages.undo_done()
    assert await repository.get_last_receipt(USER) is None


async def test_any_other_input_cancels_a_pending_undo(
    pipeline: ReceiptPipeline, telegram_client: list[dict[str, object]]
) -> None:
    await repository.insert_receipt(
        Receipt(
            telegram_user_id=USER,
            country_code="US",
            currency="USD",
            total=10.0,
            files=ReceiptFiles(original_r2_key=""),
            created_at=datetime.now(UTC),
        )
    )
    await pipeline.handle_command(USER, "/undo", "")
    await pipeline.handle_command(USER, "/status", "")  # cancels the pending undo

    session = await repository.get_session(USER)
    assert session.pending_action is None

    telegram_client.clear()
    await pipeline.handle_command(USER, "/undo", "")
    assert "again to confirm" in _last_text(telegram_client)  # asks again, doesn't delete
    assert await repository.get_last_receipt(USER) is not None


async def test_undo_is_rejected_outside_idle(
    pipeline: ReceiptPipeline, telegram_client: list[dict[str, object]]
) -> None:
    await _put_session(state=SessionState.PROCESSING)
    await pipeline.handle_command(USER, "/undo", "")
    assert "only works" in _last_text(telegram_client)


# --- file intake (spec Step 1) -----------------------------------------------


async def test_document_is_rejected_when_country_is_not_set(
    pipeline: ReceiptPipeline, telegram_client: list[dict[str, object]]
) -> None:
    await pipeline.handle_document(USER, "file-1", "application/pdf", 1000)
    assert "country" in _last_text(telegram_client).lower()
    session = await repository.get_session(USER)
    assert session.state == SessionState.IDLE


async def test_document_with_unsupported_mime_type_is_rejected(
    pipeline: ReceiptPipeline, telegram_client: list[dict[str, object]]
) -> None:
    await _set_country()
    await pipeline.handle_document(USER, "file-1", "image/gif", 1000)
    assert "can't accept" in _last_text(telegram_client)


async def test_document_over_the_size_limit_is_rejected(
    pipeline: ReceiptPipeline, telegram_client: list[dict[str, object]]
) -> None:
    await _set_country()
    await pipeline.handle_document(USER, "file-1", "application/pdf", 21 * 1024 * 1024)
    assert "too large" in _last_text(telegram_client)


async def test_document_while_processing_is_rejected_with_notice(
    pipeline: ReceiptPipeline, telegram_client: list[dict[str, object]]
) -> None:
    await _set_country()
    await _put_session(state=SessionState.PROCESSING)
    await pipeline.handle_document(USER, "file-1", "application/pdf", 1000)
    assert _last_text(telegram_client) == messages.STILL_PROCESSING


@pytest.mark.parametrize(
    "state", [SessionState.AWAITING_ANSWERS, SessionState.AWAITING_CONFIRMATION]
)
async def test_document_while_busy_is_rejected(
    pipeline: ReceiptPipeline, telegram_client: list[dict[str, object]], state: SessionState
) -> None:
    await _set_country()
    await _put_session(state=state)
    await pipeline.handle_document(USER, "file-1", "application/pdf", 1000)
    assert _last_text(telegram_client) == messages.BUSY_REJECT_FILE


async def test_compressed_photo_is_rejected_while_idle(
    pipeline: ReceiptPipeline, telegram_client: list[dict[str, object]]
) -> None:
    await pipeline.handle_compressed_photo(USER)
    assert _last_text(telegram_client) == messages.COMPRESSED_PHOTO_REJECTED


async def test_valid_document_with_no_gaps_reaches_confirmation(
    pipeline: ReceiptPipeline, telegram_client: list[dict[str, object]]
) -> None:
    await _set_country()  # DEFAULT_RESULT has no gaps
    await pipeline.handle_document(USER, "file-1", "application/pdf", 1000)

    session = await repository.get_session(USER)
    assert session.state == SessionState.AWAITING_CONFIRMATION
    assert "/confirm" in _last_text(telegram_client)
    # "Processing..." then the confirmation prompt
    assert any(m["text"] == messages.PROCESSING_STARTED for m in telegram_client)


async def test_valid_document_with_a_gap_reaches_awaiting_answers(
    pipeline: ReceiptPipeline, telegram_client: list[dict[str, object]], extractor: FakeExtractor
) -> None:
    extractor.result = RawExtraction(
        merchant_name="Fake Mart",
        date=None,
        total=10.0,
        items=[RawExtractionItem(name="a", price=10.0)],
    )
    await _set_country()
    await pipeline.handle_document(USER, "file-1", "application/pdf", 1000)

    session = await repository.get_session(USER)
    assert session.state == SessionState.AWAITING_ANSWERS
    assert session.current_question == "missing_date"
    assert "date" in _last_text(telegram_client).lower()


async def test_valid_document_with_nothing_extracted_is_refused(
    pipeline: ReceiptPipeline, telegram_client: list[dict[str, object]], extractor: FakeExtractor
) -> None:
    extractor.result = RawExtraction()
    await _set_country()
    await pipeline.handle_document(USER, "file-1", "application/pdf", 1000)

    session = await repository.get_session(USER)
    assert session.state == SessionState.IDLE
    assert _last_text(telegram_client) == messages.REFUSED


async def test_extraction_failure_returns_to_idle_with_an_error(
    pipeline: ReceiptPipeline, telegram_client: list[dict[str, object]], extractor: FakeExtractor
) -> None:
    extractor.fail = True
    await _set_country()
    await pipeline.handle_document(USER, "file-1", "application/pdf", 1000)

    session = await repository.get_session(USER)
    assert session.state == SessionState.IDLE
    assert _last_text(telegram_client) == messages.EXTRACTION_FAILED


# --- cancel during PROCESSING, then a late extraction result ------------------


async def test_cancel_during_processing_discards_a_later_extraction_result(
    pipeline: ReceiptPipeline, telegram_client: list[dict[str, object]]
) -> None:
    await _put_session(state=SessionState.PROCESSING, country_code="US", extraction_job_id="job-1")

    await pipeline.handle_command(USER, "/cancel", "")
    telegram_client.clear()

    await pipeline.handle_extraction_result(USER, "job-1")

    session = await repository.get_session(USER)
    assert session.state == SessionState.IDLE
    assert session.draft is None
    assert telegram_client == []  # discarded silently, nothing sent


async def test_extraction_result_for_a_superseded_job_id_is_discarded(
    pipeline: ReceiptPipeline, telegram_client: list[dict[str, object]]
) -> None:
    await _put_session(
        state=SessionState.PROCESSING, country_code="US", extraction_job_id="job-2", cancelled=False
    )

    await pipeline.handle_extraction_result(USER, "job-1")  # a stale, superseded job id

    session = await repository.get_session(USER)
    assert session.state == SessionState.PROCESSING  # untouched
    assert telegram_client == []


async def test_extraction_result_still_running_is_a_noop(
    pipeline: ReceiptPipeline, telegram_client: list[dict[str, object]], extractor: FakeExtractor
) -> None:
    extractor.result = None
    await _put_session(state=SessionState.PROCESSING, country_code="US", extraction_job_id="job-1")

    await pipeline.handle_extraction_result(USER, "job-1")

    session = await repository.get_session(USER)
    assert session.state == SessionState.PROCESSING
    assert telegram_client == []


# --- text handling by state (spec Section 7 table) ---------------------------


async def test_text_while_idle_gets_a_nudge(
    pipeline: ReceiptPipeline, telegram_client: list[dict[str, object]]
) -> None:
    await pipeline.handle_text(USER, "hello")
    assert _last_text(telegram_client) == messages.IDLE_TEXT_NUDGE


async def test_text_while_processing_is_ignored_with_notice(
    pipeline: ReceiptPipeline, telegram_client: list[dict[str, object]]
) -> None:
    await _put_session(state=SessionState.PROCESSING)
    await pipeline.handle_text(USER, "hello")
    assert _last_text(telegram_client) == messages.STILL_PROCESSING


# --- Step 6: answer loop -------------------------------------------------------


async def test_answer_applies_ops_and_moves_to_the_next_question(
    pipeline: ReceiptPipeline,
    telegram_client: list[dict[str, object]],
    interpreter: FakeInterpreter,
) -> None:
    from receipt_parser_backend.receipts.models import Draft

    draft = Draft(currency="USD", date=None, total=10.0, items=[Item(name="a", price=10.0)])
    await _put_session(
        state=SessionState.AWAITING_ANSWERS,
        country_code="US",
        draft=draft,
        current_question="missing_date",
        question_queue=["missing_date"],
    )
    interpreter.response = InterpreterOutput(
        intent="answer", ops=[SetOp(op="set", path="date", value="2026-01-15")]
    )

    await pipeline.handle_text(USER, "January 15th")

    session = await repository.get_session(USER)
    assert session.state == SessionState.AWAITING_CONFIRMATION
    assert session.draft is not None
    assert session.draft.date == "2026-01-15"


async def test_unclear_answer_re_asks_the_same_question(
    pipeline: ReceiptPipeline,
    telegram_client: list[dict[str, object]],
    interpreter: FakeInterpreter,
) -> None:
    from receipt_parser_backend.receipts.models import Draft

    draft = Draft(currency="USD", date=None, total=10.0, items=[Item(name="a", price=10.0)])
    await _put_session(
        state=SessionState.AWAITING_ANSWERS,
        country_code="US",
        draft=draft,
        current_question="missing_date",
        question_queue=["missing_date"],
    )
    interpreter.response = InterpreterOutput(intent="unclear")

    await pipeline.handle_text(USER, "huh?")

    session = await repository.get_session(USER)
    assert session.state == SessionState.AWAITING_ANSWERS
    assert session.current_question == "missing_date"
    assert "date" in _last_text(telegram_client).lower()


# --- Step 7: confirmation loop -------------------------------------------------


async def test_confirm_intent_from_text_persists(
    pipeline: ReceiptPipeline,
    telegram_client: list[dict[str, object]],
    interpreter: FakeInterpreter,
) -> None:
    from receipt_parser_backend.receipts.models import Draft

    draft = Draft(currency="USD", merchant_name="Fake Mart", date="2026-01-15", total=10.0)
    await _put_session(state=SessionState.AWAITING_CONFIRMATION, country_code="US", draft=draft)
    interpreter.response = InterpreterOutput(intent="confirm")

    await pipeline.handle_text(USER, "yes")

    assert _last_text(telegram_client) == messages.SAVED
    assert await repository.get_last_receipt(USER) is not None


async def test_edit_intent_applies_ops_and_stays_in_confirmation(
    pipeline: ReceiptPipeline,
    telegram_client: list[dict[str, object]],
    interpreter: FakeInterpreter,
) -> None:
    from receipt_parser_backend.receipts.models import Draft

    draft = Draft(
        currency="USD",
        merchant_name="Fake Mart",
        date="2026-01-15",
        total=10.0,
        items=[Item(name="a", price=10.0)],
    )
    await _put_session(state=SessionState.AWAITING_CONFIRMATION, country_code="US", draft=draft)
    interpreter.response = InterpreterOutput(
        intent="edit", ops=[SetOp(op="set", path="merchant_name", value="Corrected Mart")]
    )

    await pipeline.handle_text(USER, "actually it's Corrected Mart")

    session = await repository.get_session(USER)
    assert session.state == SessionState.AWAITING_CONFIRMATION
    assert session.draft is not None
    assert session.draft.merchant_name == "Corrected Mart"


async def test_edit_that_reopens_a_gap_moves_back_to_awaiting_answers(
    pipeline: ReceiptPipeline,
    telegram_client: list[dict[str, object]],
    interpreter: FakeInterpreter,
) -> None:
    from receipt_parser_backend.receipts.models import Draft

    draft = Draft(
        currency="USD",
        merchant_name="Fake Mart",
        date="2026-01-15",
        total=10.0,
        items=[Item(name="a", price=None)],
    )
    await _put_session(state=SessionState.AWAITING_CONFIRMATION, country_code="US", draft=draft)
    interpreter.response = InterpreterOutput(
        intent="edit", ops=[SetOp(op="set", path="total", value=5.0)]
    )

    await pipeline.handle_text(USER, "actually the total was 5")

    session = await repository.get_session(USER)
    # the item with a missing price still creates a gap after the edit
    assert session.state == SessionState.AWAITING_ANSWERS
    assert session.current_question is not None
    assert session.current_question.startswith("missing_item_price")


async def test_unclear_confirmation_reply_gets_the_fixed_prompt(
    pipeline: ReceiptPipeline,
    telegram_client: list[dict[str, object]],
    interpreter: FakeInterpreter,
) -> None:
    from receipt_parser_backend.receipts.models import Draft

    draft = Draft(currency="USD", merchant_name="Fake Mart", date="2026-01-15", total=10.0)
    await _put_session(state=SessionState.AWAITING_CONFIRMATION, country_code="US", draft=draft)
    interpreter.response = InterpreterOutput(intent="unclear")

    await pipeline.handle_text(USER, "what?")

    assert _last_text(telegram_client) == messages.UNCLEAR_CONFIRMATION


# --- total override rules, all three branches (spec 8.1) ---------------------


async def _put_total_mismatch_session() -> Draft:
    from receipt_parser_backend.pipeline.questions import TOTAL_MISMATCH
    from receipt_parser_backend.receipts.models import Draft

    draft = Draft(
        currency="USD",
        merchant_name="Fake Mart",
        date="2026-01-15",
        total=20.0,
        items=[Item(name="a", price=10.0)],
        total_check=TotalCheck(
            status="mismatch", item_sum=10.0, expected_total=10.0, difference=10.0
        ),
    )
    await _put_session(
        state=SessionState.AWAITING_ANSWERS,
        country_code="US",
        draft=draft,
        current_question=TOTAL_MISMATCH,
        question_queue=[TOTAL_MISMATCH],
    )
    return draft


async def test_override_branch_1_user_total_now_matches(
    pipeline: ReceiptPipeline,
    telegram_client: list[dict[str, object]],
    interpreter: FakeInterpreter,
) -> None:
    await _put_total_mismatch_session()
    interpreter.response = InterpreterOutput(
        intent="answer", ops=[SetOp(op="set", path="total", value=10.0)]
    )

    await pipeline.handle_text(USER, "actually it was 10")

    session = await repository.get_session(USER)
    assert session.state == SessionState.AWAITING_CONFIRMATION
    assert session.draft is not None
    assert session.draft.total_check is not None
    assert session.draft.total_check.status == "match"
    assert session.draft.notes == [messages.note_total_set_by_user_matches()]


async def test_override_branch_1_user_total_still_mismatches(
    pipeline: ReceiptPipeline,
    telegram_client: list[dict[str, object]],
    interpreter: FakeInterpreter,
) -> None:
    await _put_total_mismatch_session()
    interpreter.response = InterpreterOutput(
        intent="answer", ops=[SetOp(op="set", path="total", value=15.0)]
    )

    await pipeline.handle_text(USER, "it was 15")

    session = await repository.get_session(USER)
    # resolved immediately as an override - not re-queued as a question
    assert session.state == SessionState.AWAITING_CONFIRMATION
    assert session.draft is not None
    assert session.draft.total_check is not None
    assert session.draft.total_check.status == "user_override"
    assert session.draft.total == 15.0
    note = session.draft.notes[0]
    assert "15.00 USD" in note
    assert "10.00 USD" in note  # expected total from items


async def test_override_branch_2_user_accepts_the_shown_total(
    pipeline: ReceiptPipeline,
    telegram_client: list[dict[str, object]],
    interpreter: FakeInterpreter,
) -> None:
    await _put_total_mismatch_session()
    interpreter.response = InterpreterOutput(intent="accept_total")

    await pipeline.handle_text(USER, "yes it's correct as shown")

    session = await repository.get_session(USER)
    assert session.state == SessionState.AWAITING_CONFIRMATION
    assert session.draft is not None
    assert session.draft.total == 20.0  # kept, not changed
    assert session.draft.total_source == "user"
    assert session.draft.total_check is not None
    assert session.draft.total_check.status == "user_override"
    assert "confirmed" in session.draft.notes[0].lower()


async def test_override_branch_3_correcting_an_item_price_rechecks_normally(
    pipeline: ReceiptPipeline,
    telegram_client: list[dict[str, object]],
    interpreter: FakeInterpreter,
) -> None:
    await _put_total_mismatch_session()
    interpreter.response = InterpreterOutput(
        intent="answer", ops=[SetOp(op="set", path="items[0].price", value=20.0)]
    )

    await pipeline.handle_text(USER, "the item was actually 20")

    session = await repository.get_session(USER)
    assert session.state == SessionState.AWAITING_CONFIRMATION
    assert session.draft is not None
    assert session.draft.total_check is not None
    assert session.draft.total_check.status == "match"
    assert session.draft.notes == []  # no override involved


async def test_override_is_cleared_by_a_later_item_price_change(
    pipeline: ReceiptPipeline,
    telegram_client: list[dict[str, object]],
    interpreter: FakeInterpreter,
) -> None:
    # First, accept a mismatched total as an override.
    await _put_total_mismatch_session()
    interpreter.response = InterpreterOutput(intent="accept_total")
    await pipeline.handle_text(USER, "yes, correct as shown")
    session = await repository.get_session(USER)
    assert session.state == SessionState.AWAITING_CONFIRMATION
    assert session.draft is not None
    assert session.draft.total_check is not None
    assert session.draft.total_check.status == "user_override"

    # Now correct an item price from AWAITING_CONFIRMATION via /edit - the
    # override and its note must be cleared, and the check re-run fresh.
    interpreter.response = InterpreterOutput(
        intent="edit", ops=[SetOp(op="set", path="items[0].price", value=20.0)]
    )
    await pipeline.handle_text(USER, "actually the item was 20")

    session = await repository.get_session(USER)
    assert session.draft is not None
    # 20.0 item now matches the still-20.0 total - override no longer needed
    assert session.draft.total_check is not None
    assert session.draft.total_check.status == "match"
    assert session.draft.notes == []


# --- Telegram download + R2 storage (spec Step 1.4) ---------------------------


async def test_document_intake_stores_the_original_in_r2(
    pipeline: ReceiptPipeline, telegram_client: list[dict[str, object]]
) -> None:
    from receipt_parser_backend.blob_storage.client import download_bytes
    from tests.conftest import FAKE_TELEGRAM_FILE_CONTENT

    await _set_country()
    await pipeline.handle_document(USER, "file-1", "application/pdf", 1000)

    session = await repository.get_session(USER)
    r2_key = session.r2_keys.original
    assert r2_key is not None
    assert (await download_bytes(r2_key)) == FAKE_TELEGRAM_FILE_CONTENT


async def test_confirmed_receipt_carries_the_r2_key(
    pipeline: ReceiptPipeline, telegram_client: list[dict[str, object]]
) -> None:
    await _set_country()  # DEFAULT_RESULT has no gaps -> straight to AWAITING_CONFIRMATION
    await pipeline.handle_document(USER, "file-1", "application/pdf", 1000)
    session = await repository.get_session(USER)
    r2_key = session.r2_keys.original

    await pipeline.handle_command(USER, "/confirm", "")

    receipt = await repository.get_last_receipt(USER)
    assert receipt is not None
    assert receipt.files.original_r2_key == r2_key


# --- background extraction polling (spec Section 11 decision 3, Milestone 6) --


class _DelayedExtractor(FakeExtractor):
    """Returns None (still running) a fixed number of times before resolving."""

    def __init__(self, *, pending_polls: int) -> None:
        super().__init__()
        self._remaining = pending_polls

    async def fetch_result(self, job_id: str) -> RawExtraction | None:
        if self._remaining > 0:
            self._remaining -= 1
            return None
        return await super().fetch_result(job_id)


async def test_background_polling_completes_once_the_job_resolves(
    fake_repository_db: object, telegram_client: list[dict[str, object]]
) -> None:
    extractor = _DelayedExtractor(pending_polls=2)
    pipeline = ReceiptPipeline(
        extractor=extractor,
        interpreter=FakeInterpreter(),
        extraction_poll_interval_seconds=0.01,
        extraction_timeout_seconds=1.0,
    )
    await _set_country()

    await pipeline.handle_document(USER, "file-1", "application/pdf", 1000)
    assert pipeline._background_tasks  # the immediate check wasn't enough - a poll was scheduled
    await asyncio.gather(*pipeline._background_tasks)

    session = await repository.get_session(USER)
    assert session.state == SessionState.AWAITING_CONFIRMATION


async def test_background_polling_times_out_and_returns_to_idle(
    fake_repository_db: object, telegram_client: list[dict[str, object]]
) -> None:
    extractor = FakeExtractor(result=None)  # never resolves
    pipeline = ReceiptPipeline(
        extractor=extractor,
        interpreter=FakeInterpreter(),
        extraction_poll_interval_seconds=0.01,
        extraction_timeout_seconds=0.03,
    )
    await _set_country()

    await pipeline.handle_document(USER, "file-1", "application/pdf", 1000)
    await asyncio.gather(*pipeline._background_tasks)

    session = await repository.get_session(USER)
    assert session.state == SessionState.IDLE
    assert _last_text(telegram_client) == messages.EXTRACTION_FAILED


async def test_cancel_during_processing_stops_background_polling(
    fake_repository_db: object, telegram_client: list[dict[str, object]]
) -> None:
    extractor = FakeExtractor(result=None)  # never resolves on its own
    pipeline = ReceiptPipeline(
        extractor=extractor,
        interpreter=FakeInterpreter(),
        extraction_poll_interval_seconds=0.01,
        extraction_timeout_seconds=10.0,
    )
    await _set_country()

    await pipeline.handle_document(USER, "file-1", "application/pdf", 1000)
    await pipeline.handle_command(USER, "/cancel", "")
    await asyncio.gather(*pipeline._background_tasks)

    session = await repository.get_session(USER)
    assert session.state == SessionState.IDLE
    assert session.cancelled is True
