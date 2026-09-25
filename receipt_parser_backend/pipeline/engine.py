"""The state machine: Section 6 commands and Section 7 transitions.

Bound to one extractor + interpreter implementation - the real ones as of
Milestones 5-6. Telegram specifics (parsing updates, sending replies) stay in
:mod:`receipt_parser_backend.telegram`; this module only deals in plain
values (user id, command/text, file metadata) so it's testable without any
Telegram machinery.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Coroutine
from datetime import UTC, date, datetime
from typing import Any

import structlog

from receipt_parser_backend.ai.answer import AnswerPort
from receipt_parser_backend.ai.extraction import ALLOWED_MIME_TYPES, ExtractionFailed, ExtractorPort
from receipt_parser_backend.ai.interpreter import InterpreterOutput, InterpreterPort, SetOp
from receipt_parser_backend.ai.llamaextract_extractor import LlamaExtractExtractor
from receipt_parser_backend.ai.openai_answer_agent import OpenAIAnswerAgent
from receipt_parser_backend.ai.openai_interpreter import OpenAIInterpreter
from receipt_parser_backend.blob_storage.client import upload_bytes
from receipt_parser_backend.countries import CountryProfile, get_profile
from receipt_parser_backend.pipeline import messages, render
from receipt_parser_backend.pipeline.normalizer import normalize_extraction
from receipt_parser_backend.pipeline.ops import (
    ValidatedReply,
    apply_ops,
    validate_interpreter_output,
)
from receipt_parser_backend.pipeline.questions import TOTAL_MISMATCH, question_text
from receipt_parser_backend.pipeline.validator import (
    compute_total_check,
    validate_and_build_questions,
)
from receipt_parser_backend.receipts.models import (
    Draft,
    R2Keys,
    Receipt,
    ReceiptFiles,
    Session,
    SessionState,
    TotalCheck,
    UserSettings,
)
from receipt_parser_backend.reports.builder import build_report_pdf
from receipt_parser_backend.sessions import repository
from receipt_parser_backend.telegram.client import download_file, send_document, send_message

logger = structlog.get_logger(__name__)

_MAX_FILE_SIZE_BYTES = 20 * 1024 * 1024

# Milestone 1 decision: in-process polling, not a LlamaCloud webhook (see the
# open-decisions plan). 5s is plenty responsive for a single-user bot; 5
# minutes is generous slack before treating a job as failed (spec Section 10).
_DEFAULT_EXTRACTION_POLL_INTERVAL_SECONDS = 5.0
_DEFAULT_EXTRACTION_TIMEOUT_SECONDS = 300.0

_BUSY_STATES = frozenset(
    {SessionState.PROCESSING, SessionState.AWAITING_ANSWERS, SessionState.AWAITING_CONFIRMATION}
)


def _now() -> datetime:
    return datetime.now(UTC)


def _build_r2_key(user_id: int, mime_type: str) -> str:
    extension = ALLOWED_MIME_TYPES.get(mime_type, "bin")
    return f"receipts/{user_id}/{uuid.uuid4().hex}/original.{extension}"


def _parse_report_range(args: str) -> tuple[date, date] | None:
    """Parse ``"YYYY-MM-DD YYYY-MM-DD"``. None on anything malformed or out of order."""

    parts = args.split()
    if len(parts) != 2:
        return None
    try:
        start_date = date.fromisoformat(parts[0])
        end_date = date.fromisoformat(parts[1])
    except ValueError:
        return None
    if start_date > end_date:
        return None
    return start_date, end_date


def _log_interpretation(
    user_id: int,
    user_text: str,
    active_question: str | None,
    output: InterpreterOutput,
    validated: ValidatedReply,
) -> None:
    """Log why a reply ended up ``unclear`` - the two causes look identical
    from the outside (both just re-ask the same question), which made a real
    failure ("2 @ $1.99 must be removed") indistinguishable from the user
    saying something genuinely unrelated. ``rejected_by_validation=True``
    means the model tried something and Section 9.2 validation threw it out
    (bad path/type/index - see pipeline/ops.py); ``False`` means the model
    itself gave up and returned "unclear".
    """

    if validated.intent != "unclear":
        return
    logger.info(
        "interpreter.result_unclear",
        user_id=user_id,
        active_question=active_question,
        user_text=user_text,
        raw_intent=output.intent,
        raw_ops=[op.model_dump() for op in output.ops],
        rejected_by_validation=output.intent != "unclear",
    )


class ReceiptPipeline:
    """Everything a whitelisted user's command or message can trigger."""

    def __init__(
        self,
        extractor: ExtractorPort,
        interpreter: InterpreterPort,
        answer_agent: AnswerPort,
        *,
        extraction_poll_interval_seconds: float = _DEFAULT_EXTRACTION_POLL_INTERVAL_SECONDS,
        extraction_timeout_seconds: float = _DEFAULT_EXTRACTION_TIMEOUT_SECONDS,
    ) -> None:
        self._extractor = extractor
        self._interpreter = interpreter
        self._answer_agent = answer_agent
        self._extraction_poll_interval_seconds = extraction_poll_interval_seconds
        self._extraction_timeout_seconds = extraction_timeout_seconds
        # asyncio only holds a weak reference to a scheduled task; this set is
        # what keeps background polling tasks alive until they finish.
        self._background_tasks: set[asyncio.Task[None]] = set()

    async def _reply(self, user_id: int, text: str) -> None:
        await send_message(user_id, text)

    def _spawn(self, coro: Coroutine[Any, Any, None]) -> None:
        task = asyncio.create_task(coro)
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)

    # --- commands (spec Section 6) ------------------------------------------

    async def handle_command(self, user_id: int, command: str, args: str) -> None:
        session = await repository.get_session(user_id)
        if session.pending_action is not None and command != "/undo":
            session.pending_action = None
            await repository.save_session(session)

        if command == "/start":
            await self._reply(user_id, messages.START_TEXT)
        elif command == "/help":
            await self._reply(user_id, messages.HELP_TEXT)
        elif command == "/country":
            await self._cmd_country(user_id, args, session)
        elif command == "/status":
            await self._reply(
                user_id, messages.status_report(session.state.value, session.current_question)
            )
        elif command == "/show":
            await self._cmd_show(user_id, session)
        elif command == "/confirm":
            await self._cmd_confirm(user_id, session)
        elif command == "/cancel":
            await self._cmd_cancel(user_id, session)
        elif command == "/last":
            await self._cmd_last(user_id, session)
        elif command == "/undo":
            await self._cmd_undo(user_id, session)
        elif command == "/report":
            await self._cmd_report(user_id, args, session)
        else:
            await self._reply(user_id, messages.UNKNOWN_COMMAND)

    async def _cmd_country(self, user_id: int, args: str, session: Session) -> None:
        code = args.strip().upper()
        if not code:
            settings = await repository.get_user_settings(user_id)
            await self._reply(
                user_id, messages.country_shown(settings.country_code if settings else None)
            )
            return
        if session.state != SessionState.IDLE:
            await self._reply(
                user_id, messages.invalid_state_reply("/country <code>", "while idle")
            )
            return
        try:
            get_profile(code)
        except KeyError:
            await self._reply(user_id, messages.country_unsupported(code))
            return
        await repository.save_user_settings(
            UserSettings(telegram_user_id=user_id, country_code=code, updated_at=_now())
        )
        await self._reply(user_id, messages.country_set(code))

    async def _cmd_show(self, user_id: int, session: Session) -> None:
        if session.state not in (SessionState.AWAITING_ANSWERS, SessionState.AWAITING_CONFIRMATION):
            await self._reply(
                user_id,
                messages.invalid_state_reply(
                    "/show", "while a receipt is awaiting answers or confirmation"
                ),
            )
            return
        assert session.draft is not None
        if session.state == SessionState.AWAITING_ANSWERS:
            assert session.current_question is not None
            await self._reply(
                user_id, render.render_draft_with_question(session.draft, session.current_question)
            )
        else:
            await self._reply(user_id, render.render_confirmation(session.draft))

    async def _cmd_confirm(self, user_id: int, session: Session) -> None:
        if session.state != SessionState.AWAITING_CONFIRMATION:
            await self._reply(
                user_id,
                messages.invalid_state_reply("/confirm", "while reviewing the final receipt"),
            )
            return
        await self._persist_and_finish(user_id, session)

    async def _cmd_cancel(self, user_id: int, session: Session) -> None:
        if session.state not in _BUSY_STATES:
            await self._reply(
                user_id,
                messages.invalid_state_reply("/cancel", "while a receipt is being processed"),
            )
            return
        session.state = SessionState.IDLE
        session.draft = None
        session.raw_extraction = {}
        session.question_queue = []
        session.current_question = None
        session.cancelled = True  # discards a late extraction result (spec Step 2, Step 3.1)
        await repository.save_session(session)
        await self._reply(user_id, messages.CANCELLED)

    async def _cmd_last(self, user_id: int, session: Session) -> None:
        if session.state != SessionState.IDLE:
            await self._reply(user_id, messages.invalid_state_reply("/last", "while idle"))
            return
        receipt = await repository.get_last_receipt(user_id)
        if receipt is None:
            await self._reply(user_id, messages.NO_RECEIPTS_YET)
            return
        await self._reply(user_id, render.render_draft_summary(_receipt_as_draft(receipt)))

    async def _cmd_undo(self, user_id: int, session: Session) -> None:
        if session.state != SessionState.IDLE:
            await self._reply(user_id, messages.invalid_state_reply("/undo", "while idle"))
            return
        if session.pending_action == "undo":
            session.pending_action = None
            await repository.save_session(session)
            receipt = await repository.get_last_receipt(user_id)
            if receipt is None or receipt.id is None:
                await self._reply(user_id, messages.UNDO_NOTHING_TO_UNDO)
                return
            await repository.delete_receipt(receipt.id)
            await self._reply(user_id, messages.undo_done())
            return

        receipt = await repository.get_last_receipt(user_id)
        if receipt is None:
            await self._reply(user_id, messages.NO_RECEIPTS_YET)
            return
        session.pending_action = "undo"
        await repository.save_session(session)
        await self._reply(
            user_id,
            messages.undo_confirm_prompt(receipt.merchant_name, receipt.total, receipt.currency),
        )

    async def _cmd_report(self, user_id: int, args: str, session: Session) -> None:
        if session.state != SessionState.IDLE:
            await self._reply(user_id, messages.invalid_state_reply("/report", "while idle"))
            return

        parsed = _parse_report_range(args)
        if parsed is None:
            await self._reply(user_id, messages.REPORT_USAGE)
            return
        start_date, end_date = parsed

        receipts = await repository.get_categorized_receipts_in_range(
            user_id, start_date.isoformat(), end_date.isoformat()
        )
        if not receipts:
            await self._reply(user_id, messages.report_no_receipts(start_date, end_date))
            return

        try:
            pdf_bytes = await build_report_pdf(
                receipts, start_date.isoformat(), end_date.isoformat()
            )
        except Exception as exc:
            logger.warning("report.build_failed", user_id=user_id, error=repr(exc))
            await self._reply(user_id, messages.REPORT_FAILED)
            return

        filename = f"529-report-{start_date.isoformat()}-to-{end_date.isoformat()}.pdf"
        await send_document(
            user_id,
            filename,
            pdf_bytes,
            caption=messages.report_ready(start_date, end_date, len(receipts)),
        )

    # --- non-command messages (spec Section 7 table) ------------------------

    async def handle_text(self, user_id: int, text: str) -> None:
        session = await repository.get_session(user_id)
        if session.pending_action is not None:
            session.pending_action = None
            await repository.save_session(session)

        if session.state == SessionState.IDLE:
            await self._reply(user_id, messages.IDLE_TEXT_NUDGE)
        elif session.state == SessionState.PROCESSING:
            await self._reply(user_id, messages.STILL_PROCESSING)
        elif session.state == SessionState.AWAITING_ANSWERS:
            await self._handle_answer(user_id, session, text)
        else:
            await self._handle_confirmation_reply(user_id, session, text)

    async def handle_compressed_photo(self, user_id: int) -> None:
        session = await repository.get_session(user_id)
        if session.state == SessionState.IDLE:
            await self._reply(user_id, messages.COMPRESSED_PHOTO_REJECTED)
        elif session.state == SessionState.PROCESSING:
            await self._reply(user_id, messages.STILL_PROCESSING)
        else:
            await self._reply(user_id, messages.BUSY_REJECT_FILE)

    async def handle_document(
        self, user_id: int, file_id: str, mime_type: str, file_size: int
    ) -> None:
        session = await repository.get_session(user_id)

        if session.state == SessionState.PROCESSING:
            await self._reply(user_id, messages.STILL_PROCESSING)
            return
        if session.state in (SessionState.AWAITING_ANSWERS, SessionState.AWAITING_CONFIRMATION):
            await self._reply(user_id, messages.BUSY_REJECT_FILE)
            return

        settings = await repository.get_user_settings(user_id)
        if settings is None:
            await self._reply(user_id, messages.COUNTRY_NOT_SET)
            return
        if mime_type not in ALLOWED_MIME_TYPES:
            await self._reply(
                user_id, messages.unsupported_file(f"unsupported file type '{mime_type}'")
            )
            return
        if file_size > _MAX_FILE_SIZE_BYTES:
            await self._reply(
                user_id, messages.unsupported_file("the file is too large (max 20 MB)")
            )
            return

        profile = get_profile(settings.country_code)

        # Spec Step 1.4: download the original from Telegram, then store it in
        # R2 before submitting anywhere else - LlamaExtract never sees
        # anything we haven't already durably stored ourselves.
        file_bytes = await download_file(file_id)
        r2_key = _build_r2_key(user_id, mime_type)
        await upload_bytes(r2_key, file_bytes, content_type=mime_type)

        job_id = await self._extractor.submit(file_bytes, mime_type, profile)
        session.state = SessionState.PROCESSING
        session.country_code = settings.country_code
        session.extraction_job_id = job_id
        session.cancelled = False
        session.draft = None
        session.raw_extraction = {}
        session.question_queue = []
        session.current_question = None
        session.r2_keys = R2Keys(original=r2_key, original_content_type=mime_type)
        await repository.save_session(session)
        await self._reply(user_id, messages.PROCESSING_STARTED)

        # An immediate check resolves fast/already-cached jobs (and every fake
        # extractor in tests) without waiting a full poll interval; anything
        # still running continues in the background so the webhook request
        # that triggered this can return right away (spec Step 0.5).
        done = await self.handle_extraction_result(user_id, job_id)
        if not done:
            self._spawn(self._poll_extraction(user_id, job_id))

    # --- extraction completion (spec Step 3) --------------------------------

    async def handle_extraction_result(self, user_id: int, job_id: str) -> bool:
        """Check ``job_id``'s result and act on it if ready.

        Returns True once this job needs no more polling: it was discarded,
        it failed, or a result arrived and the draft moved on. False means
        it's still running - keep polling.
        """

        session = await repository.get_session(user_id)
        if session.cancelled or session.extraction_job_id != job_id:
            return True  # spec Step 3.1: discard - cancelled, or superseded by a newer job

        try:
            raw = await self._extractor.fetch_result(job_id)
        except ExtractionFailed:
            session.state = SessionState.IDLE
            session.extraction_job_id = None
            await repository.save_session(session)
            await self._reply(user_id, messages.EXTRACTION_FAILED)
            return True

        if raw is None:
            return False  # still running

        assert session.country_code is not None
        profile = get_profile(session.country_code)
        session.raw_extraction = raw.model_dump()
        session.draft = normalize_extraction(raw, profile)
        await self._revalidate_and_transition(user_id, session)
        return True

    async def _poll_extraction(self, user_id: int, job_id: str) -> None:
        """Background loop: keep checking ``job_id`` until it resolves or times out."""

        elapsed = 0.0
        while elapsed < self._extraction_timeout_seconds:
            await asyncio.sleep(self._extraction_poll_interval_seconds)
            elapsed += self._extraction_poll_interval_seconds
            if await self.handle_extraction_result(user_id, job_id):
                return
        await self._timeout_extraction(user_id, job_id)

    async def _timeout_extraction(self, user_id: int, job_id: str) -> None:
        """Spec Section 10: a timeout is handled the same as a failure."""

        session = await repository.get_session(user_id)
        if session.cancelled or session.extraction_job_id != job_id:
            return
        session.state = SessionState.IDLE
        session.extraction_job_id = None
        await repository.save_session(session)
        await self._reply(user_id, messages.EXTRACTION_FAILED)

    # --- answer/confirmation loops (spec Steps 6-7) -------------------------

    async def _handle_answer(self, user_id: int, session: Session, text: str) -> None:
        assert session.draft is not None
        assert session.current_question is not None
        assert session.country_code is not None
        profile = get_profile(session.country_code)

        output = await self._interpreter.interpret(
            state=session.state,
            draft=session.draft,
            active_question=session.current_question,
            interpreter_prompt=profile.interpreter_prompt,
            user_text=text,
        )
        validated = validate_interpreter_output(
            output,
            state=session.state,
            active_question=session.current_question,
            item_count=len(session.draft.items),
        )
        _log_interpretation(user_id, text, session.current_question, output, validated)

        if validated.intent == "answer":
            answering_total_mismatch = session.current_question == TOTAL_MISMATCH
            sets_total = any(isinstance(op, SetOp) and op.path == "total" for op in validated.ops)
            session.draft = apply_ops(session.draft, validated.ops)
            if answering_total_mismatch and sets_total:
                # Spec 8.1, bullet 1: a user-given total either now matches
                # (plain note) or still doesn't (an override), but either way
                # it's resolved without re-asking.
                self._set_total_from_user_answer(session.draft, profile)
            await self._revalidate_and_transition(user_id, session)
        elif validated.intent == "accept_total":
            # Spec 8.1, bullet 2: the user accepts the mismatch as-is.
            self._accept_total_override(session.draft, profile)
            await self._revalidate_and_transition(user_id, session)
        elif validated.intent == "query":
            await self._answer_query(user_id, session.draft, profile, text)
        else:
            await self._reply(user_id, question_text(session.current_question, session.draft))

    async def _answer_query(
        self, user_id: int, draft: Draft, profile: CountryProfile, question: str
    ) -> None:
        """Read-only Q&A (the third AI touchpoint - see ai/answer.py). No
        state change, no draft mutation - just a reply."""

        answer = await self._answer_agent.answer(
            draft=draft, question=question, country_instructions=profile.interpreter_prompt
        )
        await self._reply(user_id, answer)

    def _set_total_from_user_answer(self, draft: Draft, profile: CountryProfile) -> None:
        check = compute_total_check(draft, profile)
        if check.status == "match":
            draft.total_check = check
            draft.notes = [messages.note_total_set_by_user_matches()]
            return
        assert draft.total is not None
        draft.total_check = TotalCheck(
            status="user_override",
            item_sum=check.item_sum,
            expected_total=check.expected_total,
            difference=check.difference,
        )
        draft.notes = [
            messages.note_total_set_by_user_mismatch(
                draft.total, check.expected_total, check.difference, draft.currency
            )
        ]

    def _accept_total_override(self, draft: Draft, profile: CountryProfile) -> None:
        check = compute_total_check(draft, profile)
        draft.total_source = "user"
        assert draft.total is not None
        draft.total_check = TotalCheck(
            status="user_override",
            item_sum=check.item_sum,
            expected_total=check.expected_total,
            difference=check.difference,
        )
        draft.notes = [
            messages.note_total_override_accepted(
                draft.total, check.expected_total, check.difference, draft.currency
            )
        ]

    async def _handle_confirmation_reply(self, user_id: int, session: Session, text: str) -> None:
        assert session.draft is not None
        assert session.country_code is not None
        profile = get_profile(session.country_code)

        output = await self._interpreter.interpret(
            state=session.state,
            draft=session.draft,
            active_question=None,
            interpreter_prompt=profile.interpreter_prompt,
            user_text=text,
        )
        validated = validate_interpreter_output(
            output, state=session.state, active_question=None, item_count=len(session.draft.items)
        )
        _log_interpretation(user_id, text, None, output, validated)

        if validated.intent == "confirm":
            await self._persist_and_finish(user_id, session)
        elif validated.intent == "edit":
            session.draft = apply_ops(session.draft, validated.ops)
            await self._revalidate_and_transition(user_id, session)
        elif validated.intent == "query":
            await self._answer_query(user_id, session.draft, profile, text)
        else:
            await self._reply(user_id, messages.UNCLEAR_CONFIRMATION)

    # --- shared: re-run Step 5 and move to the right state ------------------

    async def _revalidate_and_transition(self, user_id: int, session: Session) -> None:
        assert session.draft is not None
        assert session.country_code is not None
        profile = get_profile(session.country_code)
        result = validate_and_build_questions(session.draft, profile)

        if result.refused:
            session.state = SessionState.IDLE
            session.draft = None
            session.raw_extraction = {}
            session.question_queue = []
            session.current_question = None
            await repository.save_session(session)
            await self._reply(user_id, messages.REFUSED)
            return

        session.question_queue = result.question_queue
        if result.question_queue:
            session.state = SessionState.AWAITING_ANSWERS
            session.current_question = result.question_queue[0]
            await repository.save_session(session)
            await self._reply(
                user_id, render.render_draft_with_question(session.draft, session.current_question)
            )
        else:
            session.state = SessionState.AWAITING_CONFIRMATION
            session.current_question = None
            await repository.save_session(session)
            await self._reply(user_id, render.render_confirmation(session.draft))

    async def _persist_and_finish(self, user_id: int, session: Session) -> None:
        assert session.draft is not None
        assert session.country_code is not None
        draft = session.draft
        receipt = Receipt(
            telegram_user_id=user_id,
            country_code=session.country_code,
            merchant_name=draft.merchant_name,
            currency=draft.currency,
            date=draft.date,
            time=draft.time,
            items=draft.items,
            discounts=draft.discounts,
            tax=draft.tax,
            total=draft.total,
            total_source=draft.total_source,
            total_check=draft.total_check,
            notes=draft.notes,
            category=draft.category,
            files=ReceiptFiles(
                # Set in handle_document (spec Step 1.4) before extraction was
                # even submitted; empty only if a session was hand-built
                # without going through intake (e.g. some tests).
                original_r2_key=session.r2_keys.original or "",
                preprocessed_r2_key=session.r2_keys.preprocessed,
                original_content_type=session.r2_keys.original_content_type,
            ),
            raw_extraction=session.raw_extraction,
            created_at=_now(),
        )
        await repository.insert_receipt(receipt)

        session.state = SessionState.IDLE
        session.draft = None
        session.raw_extraction = {}
        session.question_queue = []
        session.current_question = None
        session.extraction_job_id = None
        session.cancelled = False
        await repository.save_session(session)
        await self._reply(user_id, messages.SAVED)


def _receipt_as_draft(receipt: Receipt) -> Draft:
    return Draft(
        merchant_name=receipt.merchant_name,
        currency=receipt.currency,
        date=receipt.date,
        time=receipt.time,
        items=receipt.items,
        discounts=receipt.discounts,
        tax=receipt.tax,
        total=receipt.total,
        total_source=receipt.total_source,
        total_check=receipt.total_check,
        notes=receipt.notes,
    )


default_pipeline = ReceiptPipeline(
    extractor=LlamaExtractExtractor(),
    interpreter=OpenAIInterpreter(),
    answer_agent=OpenAIAnswerAgent(),
)
