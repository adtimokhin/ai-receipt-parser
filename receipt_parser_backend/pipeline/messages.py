"""Static, country-independent message templates (spec Section 6, Steps 0-8, 10).

All user-facing text is a template, never AI-written (design rule 4).
"""

from __future__ import annotations

from receipt_parser_backend.countries import supported_codes

START_TEXT = (
    "Hi! Send me a receipt as a file (not a compressed photo) and I'll turn it "
    "into a structured record. Set your country first with /country, e.g. "
    "/country US. Send /help to see every command."
)

HELP_TEXT = (
    "/start - greeting and how-to\n"
    "/help - this list\n"
    "/country [CODE] - show or set your country (set only while idle)\n"
    "/status - current state and active question, if any\n"
    "/show - re-display the current draft\n"
    "/confirm - save the draft\n"
    "/cancel - stop processing or discard the draft\n"
    "/last - show your most recently saved receipt\n"
    "/undo - delete your most recently saved receipt"
)

COUNTRY_NOT_SET = "Please set a country first with /country, e.g. /country US."
COMPRESSED_PHOTO_REJECTED = "Please resend that as a file (not a compressed photo)."
PROCESSING_STARTED = "Processing your receipt…"
STILL_PROCESSING = "Still processing, your message was ignored."
BUSY_REJECT_FILE = "Finish the current receipt or send /cancel first."
CANCELLED = "Cancelled."
SAVED = "Saved."
REFUSED = "I couldn't read that receipt - no date, items, total, or merchant name came through."
EXTRACTION_FAILED = "Sorry, I couldn't process that receipt. Please try sending it again."
UNCLEAR_CONFIRMATION = "Reply yes to save, or tell me what to change."
IDLE_TEXT_NUDGE = "Send a receipt as a file to get started, or /help for commands."
UNKNOWN_COMMAND = "Unknown command. Send /help to see what's available."
NO_RECEIPTS_YET = "You don't have any saved receipts yet."
UNDO_NOTHING_TO_UNDO = "There's nothing to undo."


def unsupported_file(reason: str) -> str:
    return f"I can't accept that file: {reason}."


def invalid_state_reply(command: str, valid_states_description: str) -> str:
    return f"{command} only works {valid_states_description}."


def country_shown(active_code: str | None) -> str:
    supported = ", ".join(supported_codes())
    active = active_code or "not set"
    return f"Active country: {active}. Supported: {supported}."


def country_set(code: str) -> str:
    return f"Country set to {code}."


def country_unsupported(code: str) -> str:
    supported = ", ".join(supported_codes())
    return f"'{code}' isn't a supported country. Supported: {supported}."


def status_report(state: str, active_question: str | None) -> str:
    if active_question is None:
        return f"State: {state}."
    return f"State: {state}. Active question: {active_question}."


def undo_confirm_prompt(merchant_name: str | None, total: float | None, currency: str) -> str:
    label = merchant_name or "this receipt"
    amount = f"{total:.2f} {currency}" if total is not None else "an unknown amount"
    return f"Delete the last saved receipt ({label}, {amount})? Send /undo again to confirm."


def undo_done() -> str:
    return "Deleted."


def note_total_set_by_user_matches() -> str:
    """Spec 8.1, bullet 1: the user's total now matches the items."""

    return "Total was set by the user, not extracted."


def note_total_set_by_user_mismatch(
    reported: float, expected: float, difference: float, currency: str
) -> str:
    """Spec 8.1, bullet 1: the user's total still doesn't match - an override."""

    return (
        f"Total was set by the user, not extracted. "
        f"User-reported total: {reported:.2f} {currency}. "
        f"Expected total from items: {expected:.2f} {currency}. "
        f"Difference: {difference:.2f} {currency}."
    )


def note_total_override_accepted(
    reported: float, expected: float, difference: float, currency: str
) -> str:
    """Spec 8.1, bullet 2: the user confirmed the shown total despite a mismatch."""

    return (
        f"The user confirmed the total is correct as shown, despite a mismatch. Reported total: "
        f"{reported:.2f} {currency}. Expected total from items: {expected:.2f} {currency}. "
        f"Difference: {difference:.2f} {currency}."
    )
