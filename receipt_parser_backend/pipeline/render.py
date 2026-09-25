"""Draft and final-receipt rendering (spec Step 5.4-5.5, Step 7).

All user-facing text is a template, never AI-written (design rule 4).
"""

from __future__ import annotations

from receipt_parser_backend.pipeline.questions import question_text
from receipt_parser_backend.receipts.models import Draft


def _format_amount(value: float | None, currency: str) -> str:
    return f"{value:.2f} {currency}" if value is not None else "?"


def render_draft_summary(draft: Draft) -> str:
    """Render the draft's current fields (used by ``/show`` and after each answer)."""

    lines = [
        f"Merchant: {draft.merchant_name or '?'}",
        f"Date: {draft.date or '?'}",
        f"Time: {draft.time or '?'}",
        "Items:",
    ]
    if draft.items:
        for item in draft.items:
            price = _format_amount(item.price, draft.currency)
            lines.append(f"  - {item.name or '?'}: {price}")
    else:
        lines.append("  (none)")
    lines.append(f"Discounts: {_format_amount(draft.discounts, draft.currency)}")
    lines.append(f"Tax: {_format_amount(draft.tax, draft.currency)}")
    lines.append(f"Total: {_format_amount(draft.total, draft.currency)}")
    if draft.category is not None:
        lines.append(f"Category: {draft.category}")
    return "\n".join(lines)


def render_draft_with_question(draft: Draft, active_question: str) -> str:
    """Draft summary plus the active question (spec Step 5.4)."""

    return f"{render_draft_summary(draft)}\n\n{question_text(active_question, draft)}"


def render_confirmation(draft: Draft) -> str:
    """Final receipt plus a confirmation prompt (spec Step 5.5)."""

    return (
        f"Here's what I have:\n\n{render_draft_summary(draft)}\n\n"
        "Reply /confirm to save, or tell me what to change."
    )
