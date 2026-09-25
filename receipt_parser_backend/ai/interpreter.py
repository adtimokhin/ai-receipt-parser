"""Reply interpreter port (spec Section 9.2) - the second AI touchpoint.

``InterpreterOutput`` and its ops are the second model whose field
descriptions matter operationally, not just as documentation: they're what
gets serialized into the structured-output schema the real interpreter
(Milestone 5) sends to the LLM. Unlike extraction, the interpreter is expected
to hand back already-canonical values (ISO dates, plain numbers, ISO currency
codes) - its country prompt (spec 5.2) is what teaches it to parse "20/9" or
"3,49" correctly before it ever reaches this schema.

Code still never trusts this output blindly: :mod:`receipt_parser_backend.pipeline.ops`
implements the Section 9.2 validation (allowlist, index bounds, type checks)
that must pass before any op is applied.
"""

from __future__ import annotations

from typing import Literal, Protocol

from pydantic import BaseModel, Field

from receipt_parser_backend.receipts.models import Draft, SessionState


class SetOp(BaseModel):
    """Replace a single field's value."""

    op: Literal["set"] = Field(description="Replace a single field's value.")
    path: str = Field(
        description=(
            "The field to update. Must be one of: merchant_name, currency, "
            "date, time, items[n].name, items[n].price, discounts, tax, total "
            "- where n is a zero-based index into the current item list."
        )
    )
    value: str | float = Field(
        description=(
            "The new value, already in canonical form matching the field's "
            "type: an ISO 8601 date ('YYYY-MM-DD'), a 24-hour 'HH:MM' time, a "
            "plain non-negative number, or an uppercase ISO 4217 currency code."
        )
    )


class AddItemValue(BaseModel):
    """The new item to append."""

    name: str | None = Field(
        default=None, description="The new item's name, or null if the user didn't give one."
    )
    price: float | None = Field(
        default=None, description="The new item's price, or null if the user didn't give one."
    )


class AddItemOp(BaseModel):
    """Append a new item to the receipt."""

    op: Literal["add_item"] = Field(description="Append a new item to the receipt.")
    value: AddItemValue = Field(description="The item to add.")


class RemoveItemOp(BaseModel):
    """Delete an existing item."""

    op: Literal["remove_item"] = Field(description="Delete an existing item.")
    index: int = Field(description="Zero-based index into the draft's current item list.")


# Not a discriminated union (no Field(discriminator=...)): pydantic renders
# that as JSON Schema "oneOf" + "discriminator", which OpenAI's Structured
# Outputs API rejects outright ("'oneOf' is not permitted") - confirmed via a
# real 400 from the API, not just local schema generation. A plain union
# renders as "anyOf" instead, which OpenAI does accept, and pydantic's own
# "smart" union validation still matches each variant correctly via its
# `op` Literal tag - discriminator or not.
Op = SetOp | AddItemOp | RemoveItemOp


class InterpreterOutput(BaseModel):
    """Interpreter output schema (spec 9.2). Untrusted until validated."""

    intent: Literal["answer", "accept_total", "confirm", "edit", "query", "unclear"] = Field(
        description=(
            "What the user's reply means. 'answer' supplies a missing value or "
            "corrects a field while a question is active (spec Step 6). "
            "'accept_total' confirms a mismatched total is correct as shown - "
            "only meaningful when the active question is total_mismatch. "
            "'confirm' and 'edit' apply only during final review (spec Step 7): "
            "'confirm' accepts the receipt as shown, 'edit' changes a field on "
            "it. 'query' means the user is asking a question about the current "
            "data rather than changing or confirming anything - it never carries "
            "ops; a separate step answers it directly. 'unclear' means the reply "
            "doesn't map to any of the above - use it rather than guessing."
        )
    )
    ops: list[Op] = Field(
        default_factory=list,
        description=(
            "Edits to apply to the draft, in the order they should be applied. "
            "Always empty for intents that don't edit the draft directly "
            "(accept_total, confirm, unclear)."
        ),
    )


class InterpreterPort(Protocol):
    """The reply interpreter AI touchpoint (spec 9.2)."""

    async def interpret(
        self,
        *,
        state: SessionState,
        draft: Draft,
        active_question: str | None,
        interpreter_prompt: str,
        user_text: str,
    ) -> InterpreterOutput:
        """Map free text to a structured intent given the current draft/question."""
        ...
