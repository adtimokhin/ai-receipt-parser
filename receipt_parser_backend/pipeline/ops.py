"""Interpreter output validation and application (spec Section 9.2).

The interpreter is expected to already hand back canonical values (its
country prompt teaches it to parse local dates/numbers itself), so this is
pure validation - format and bounds checks - not parsing. Any failure turns
the whole response into ``unclear``; ops are never partially applied.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from receipt_parser_backend.ai.interpreter import (
    AddItemOp,
    InterpreterOutput,
    Op,
    RemoveItemOp,
    SetOp,
)
from receipt_parser_backend.receipts.models import Draft, Item, SessionState

ALLOWED_INTENTS_BY_STATE: dict[SessionState, frozenset[str]] = {
    SessionState.AWAITING_ANSWERS: frozenset({"answer", "accept_total", "query", "unclear"}),
    SessionState.AWAITING_CONFIRMATION: frozenset({"confirm", "edit", "query", "unclear"}),
}

_ITEM_PATH_RE = re.compile(r"^items\[(\d+)\]\.(name|price)$")
_SIMPLE_PATHS = {"merchant_name", "currency", "date", "time", "discounts", "tax", "total"}
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_TIME_RE = re.compile(r"^\d{2}:\d{2}$")
_CURRENCY_RE = re.compile(r"^[A-Za-z]{3}$")


@dataclass(frozen=True)
class ValidatedReply:
    """The effective, code-trusted intent and ops after Section 9.2 validation."""

    intent: str
    ops: list[Op]


def validate_interpreter_output(
    output: InterpreterOutput,
    *,
    state: SessionState,
    active_question: str | None,
    item_count: int,
) -> ValidatedReply:
    """Validate ``output`` against spec 9.2's rules. Any failure becomes ``unclear``."""

    allowed = ALLOWED_INTENTS_BY_STATE.get(state, frozenset())
    if output.intent not in allowed:
        return ValidatedReply(intent="unclear", ops=[])

    if output.intent == "accept_total" and active_question != "total_mismatch":
        return ValidatedReply(intent="unclear", ops=[])

    if output.intent in ("answer", "edit"):
        for op in output.ops:
            if not _op_is_valid(op, item_count=item_count):
                return ValidatedReply(intent="unclear", ops=[])
        return ValidatedReply(intent=output.intent, ops=output.ops)

    return ValidatedReply(intent=output.intent, ops=[])


def apply_ops(draft: Draft, ops: list[Op]) -> Draft:
    """Return a new draft with ``ops`` applied in order. Never partial - validate first."""

    updated = draft.model_copy(deep=True)
    for op in ops:
        _apply_op(updated, op)
    return updated


def _op_is_valid(op: Op, *, item_count: int) -> bool:
    if isinstance(op, SetOp):
        return _set_op_is_valid(op, item_count=item_count)
    if isinstance(op, AddItemOp):
        return True
    if isinstance(op, RemoveItemOp):
        return 0 <= op.index < item_count
    return False


def _set_op_is_valid(op: SetOp, *, item_count: int) -> bool:
    item_match = _ITEM_PATH_RE.match(op.path)
    if item_match:
        index, field = int(item_match.group(1)), item_match.group(2)
        if not (0 <= index < item_count):
            return False
        if field == "name":
            return isinstance(op.value, str)
        return _is_non_negative_number(op.value)

    if op.path not in _SIMPLE_PATHS:
        return False
    if op.path == "date":
        return isinstance(op.value, str) and bool(_DATE_RE.match(op.value))
    if op.path == "time":
        return isinstance(op.value, str) and bool(_TIME_RE.match(op.value))
    if op.path == "currency":
        return isinstance(op.value, str) and bool(_CURRENCY_RE.match(op.value))
    if op.path in ("discounts", "tax", "total"):
        return _is_non_negative_number(op.value)
    return isinstance(op.value, str)  # merchant_name


def _is_non_negative_number(value: object) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, int | float):
        return value >= 0
    if isinstance(value, str):
        try:
            return float(value) >= 0
        except ValueError:
            return False
    return False


def _apply_op(draft: Draft, op: Op) -> None:
    if isinstance(op, SetOp):
        _apply_set(draft, op)
    elif isinstance(op, AddItemOp):
        draft.items.append(Item(name=op.value.name, price=op.value.price))
        _clear_total_override(draft)
    elif isinstance(op, RemoveItemOp):
        del draft.items[op.index]
        _clear_total_override(draft)


def _apply_set(draft: Draft, op: SetOp) -> None:
    item_match = _ITEM_PATH_RE.match(op.path)
    if item_match:
        index, field = int(item_match.group(1)), item_match.group(2)
        item = draft.items[index]
        if field == "name":
            item.name = str(op.value)
        else:
            item.price = float(op.value)
            _clear_total_override(draft)
        return

    if op.path == "merchant_name":
        draft.merchant_name = str(op.value)
    elif op.path == "currency":
        draft.currency = str(op.value).upper()
    elif op.path == "date":
        draft.date = str(op.value)
    elif op.path == "time":
        draft.time = str(op.value)
    elif op.path == "discounts":
        draft.discounts = float(op.value)
        _clear_total_override(draft)
    elif op.path == "tax":
        draft.tax = float(op.value)
        _clear_total_override(draft)
    elif op.path == "total":
        draft.total = float(op.value)
        draft.total_source = "user"
        _clear_total_override(draft)


def _clear_total_override(draft: Draft) -> None:
    """Spec 8.1: an item price, discount, tax, or total changed - clear any
    override and its note. The generic Step 5.3 re-check (validator.py) then
    recomputes a fresh, unresolved status from these numbers."""

    draft.total_check = None
    draft.notes = []
