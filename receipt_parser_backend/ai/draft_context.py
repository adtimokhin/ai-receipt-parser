"""Shared draft rendering for AI prompts (the interpreter and the answer agent).

Both need the same explicitly-indexed view of the draft's items: the model
needs an item's exact index for an op, or to reference it precisely in an
answer, and a bare JSON array forces it to count array positions itself -
unreliable once there are more than a couple of items (see the interpreter's
own history of silently giving up rather than risk a wrong index).
"""

from __future__ import annotations

from receipt_parser_backend.receipts.models import Draft


def render_draft_for_prompt(draft: Draft) -> str:
    """Draft fields plus an "index: name - price" item list."""

    lines = [
        f"merchant_name: {draft.merchant_name!r}",
        f"currency: {draft.currency!r}",
        f"date: {draft.date!r}",
        f"time: {draft.time!r}",
        f"discounts: {draft.discounts!r}",
        f"tax: {draft.tax!r}",
        f"total: {draft.total!r}",
        "items (index: name - price):",
    ]
    for index, item in enumerate(draft.items):
        price = "null" if item.price is None else f"{item.price} {draft.currency}"
        lines.append(f"  {index}: {item.name!r} - {price}")
    return "\n".join(lines)
