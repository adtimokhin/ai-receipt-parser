"""Question templates (spec Step 5 table).

Question ids are plain strings for ``missing_date``, ``missing_total``, and
``total_mismatch``. ``missing_item_price`` can fire once per item, so its id
carries the item's index: ``missing_item_price:<index>``.
"""

from __future__ import annotations

from receipt_parser_backend.receipts.models import Draft

MISSING_DATE = "missing_date"
MISSING_TOTAL = "missing_total"
TOTAL_MISMATCH = "total_mismatch"
_MISSING_ITEM_PRICE_PREFIX = "missing_item_price"


def missing_item_price_question_id(index: int) -> str:
    return f"{_MISSING_ITEM_PRICE_PREFIX}:{index}"


def parse_question_id(question_id: str) -> tuple[str, int | None]:
    """Split a question id into its type and, for item questions, the item index."""

    kind, sep, rest = question_id.partition(":")
    if sep and kind == _MISSING_ITEM_PRICE_PREFIX:
        return kind, int(rest)
    return question_id, None


def question_text(question_id: str, draft: Draft) -> str:
    """Render the question template for ``question_id`` against ``draft``."""

    kind, index = parse_question_id(question_id)
    if kind == MISSING_DATE:
        return "I couldn't find the date on this receipt. What date was the purchase?"
    if kind == MISSING_TOTAL:
        return "I couldn't find the total. What was the total amount paid?"
    if kind == _MISSING_ITEM_PRICE_PREFIX and index is not None:
        item_label = draft.items[index].name or "an item"
        return f'I couldn\'t read the price for "{item_label}". What was it?'
    if kind == TOTAL_MISMATCH:
        assert draft.total_check is not None  # only ever queued once the check has run
        return (
            f"The items add up to {draft.total_check.expected_total:.2f} {draft.currency}, "
            f"but the receipt total reads {draft.total:.2f} {draft.currency}. You can correct "
            "an item price, give me the correct total, or reply that the total is correct as shown."
        )
    raise ValueError(f"unknown question id: {question_id!r}")
