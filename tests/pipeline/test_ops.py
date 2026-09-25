"""Interpreter output validation and application (spec Section 9.2)."""

from __future__ import annotations

from receipt_parser_backend.ai.interpreter import (
    AddItemOp,
    AddItemValue,
    InterpreterOutput,
    RemoveItemOp,
    SetOp,
)
from receipt_parser_backend.pipeline.ops import apply_ops, validate_interpreter_output
from receipt_parser_backend.receipts.models import Draft, Item, SessionState


def _draft(**kwargs: object) -> Draft:
    return Draft(currency="USD", **kwargs)


# --- intent allowlisting by state -------------------------------------------


def test_confirm_intent_is_unclear_during_awaiting_answers() -> None:
    output = InterpreterOutput(intent="confirm")
    result = validate_interpreter_output(
        output, state=SessionState.AWAITING_ANSWERS, active_question="missing_date", item_count=0
    )
    assert result.intent == "unclear"


def test_answer_intent_is_unclear_during_awaiting_confirmation() -> None:
    output = InterpreterOutput(intent="answer")
    result = validate_interpreter_output(
        output, state=SessionState.AWAITING_CONFIRMATION, active_question=None, item_count=0
    )
    assert result.intent == "unclear"


def test_edit_intent_is_allowed_during_awaiting_confirmation() -> None:
    output = InterpreterOutput(
        intent="edit", ops=[SetOp(op="set", path="merchant_name", value="Fake Mart")]
    )
    result = validate_interpreter_output(
        output, state=SessionState.AWAITING_CONFIRMATION, active_question=None, item_count=0
    )
    assert result.intent == "edit"


def test_unclear_intent_is_allowed_in_every_state() -> None:
    output = InterpreterOutput(intent="unclear")
    for state in (SessionState.AWAITING_ANSWERS, SessionState.AWAITING_CONFIRMATION):
        assert (
            validate_interpreter_output(
                output, state=state, active_question=None, item_count=0
            ).intent
            == "unclear"
        )


def test_query_intent_is_allowed_in_every_state_and_carries_no_ops() -> None:
    output = InterpreterOutput(intent="query")
    for state in (SessionState.AWAITING_ANSWERS, SessionState.AWAITING_CONFIRMATION):
        result = validate_interpreter_output(
            output, state=state, active_question=None, item_count=0
        )
        assert result.intent == "query"
        assert result.ops == []


# --- accept_total is only valid for the total_mismatch question ------------


def test_accept_total_is_unclear_when_active_question_is_not_total_mismatch() -> None:
    output = InterpreterOutput(intent="accept_total")
    result = validate_interpreter_output(
        output, state=SessionState.AWAITING_ANSWERS, active_question="missing_date", item_count=0
    )
    assert result.intent == "unclear"


def test_accept_total_is_valid_when_active_question_is_total_mismatch() -> None:
    output = InterpreterOutput(intent="accept_total")
    result = validate_interpreter_output(
        output, state=SessionState.AWAITING_ANSWERS, active_question="total_mismatch", item_count=0
    )
    assert result.intent == "accept_total"


# --- op validation: paths, types, bounds ------------------------------------


def test_set_op_on_allowed_simple_path_is_valid() -> None:
    output = InterpreterOutput(
        intent="answer", ops=[SetOp(op="set", path="date", value="2026-01-15")]
    )
    result = validate_interpreter_output(
        output, state=SessionState.AWAITING_ANSWERS, active_question="missing_date", item_count=0
    )
    assert result.intent == "answer"


def test_set_op_on_disallowed_path_is_unclear() -> None:
    output = InterpreterOutput(intent="answer", ops=[SetOp(op="set", path="notes", value="x")])
    result = validate_interpreter_output(
        output, state=SessionState.AWAITING_ANSWERS, active_question="missing_date", item_count=0
    )
    assert result.intent == "unclear"


def test_set_date_with_bad_format_is_unclear() -> None:
    output = InterpreterOutput(
        intent="answer", ops=[SetOp(op="set", path="date", value="01/15/2026")]
    )
    result = validate_interpreter_output(
        output, state=SessionState.AWAITING_ANSWERS, active_question="missing_date", item_count=0
    )
    assert result.intent == "unclear"


def test_set_time_with_bad_format_is_unclear() -> None:
    output = InterpreterOutput(intent="answer", ops=[SetOp(op="set", path="time", value="12pm")])
    result = validate_interpreter_output(
        output, state=SessionState.AWAITING_ANSWERS, active_question="missing_date", item_count=0
    )
    assert result.intent == "unclear"


def test_set_negative_total_is_unclear() -> None:
    output = InterpreterOutput(intent="answer", ops=[SetOp(op="set", path="total", value=-5.0)])
    result = validate_interpreter_output(
        output, state=SessionState.AWAITING_ANSWERS, active_question="missing_total", item_count=0
    )
    assert result.intent == "unclear"


def test_set_item_price_out_of_range_index_is_unclear() -> None:
    output = InterpreterOutput(
        intent="answer", ops=[SetOp(op="set", path="items[3].price", value=1.0)]
    )
    result = validate_interpreter_output(
        output, state=SessionState.AWAITING_ANSWERS, active_question="missing_date", item_count=2
    )
    assert result.intent == "unclear"


def test_set_item_price_in_range_index_is_valid() -> None:
    output = InterpreterOutput(
        intent="answer", ops=[SetOp(op="set", path="items[1].price", value=3.49)]
    )
    result = validate_interpreter_output(
        output, state=SessionState.AWAITING_ANSWERS, active_question="missing_date", item_count=2
    )
    assert result.intent == "answer"


def test_remove_item_out_of_range_index_is_unclear() -> None:
    output = InterpreterOutput(intent="edit", ops=[RemoveItemOp(op="remove_item", index=5)])
    result = validate_interpreter_output(
        output, state=SessionState.AWAITING_CONFIRMATION, active_question=None, item_count=2
    )
    assert result.intent == "unclear"


def test_add_item_is_always_valid() -> None:
    output = InterpreterOutput(
        intent="edit", ops=[AddItemOp(op="add_item", value=AddItemValue(name="Eggs", price=4.99))]
    )
    result = validate_interpreter_output(
        output, state=SessionState.AWAITING_CONFIRMATION, active_question=None, item_count=0
    )
    assert result.intent == "edit"


def test_one_invalid_op_among_several_makes_the_whole_reply_unclear() -> None:
    output = InterpreterOutput(
        intent="edit",
        ops=[
            SetOp(op="set", path="merchant_name", value="Fake Mart"),
            SetOp(op="set", path="total", value=-1.0),
        ],
    )
    result = validate_interpreter_output(
        output, state=SessionState.AWAITING_CONFIRMATION, active_question=None, item_count=0
    )
    assert result.intent == "unclear"
    assert result.ops == []


def test_confirm_and_accept_total_never_carry_ops() -> None:
    output = InterpreterOutput(intent="confirm", ops=[])
    result = validate_interpreter_output(
        output, state=SessionState.AWAITING_CONFIRMATION, active_question=None, item_count=0
    )
    assert result.ops == []


# --- applying validated ops --------------------------------------------------


def test_apply_set_simple_field() -> None:
    draft = _draft(merchant_name=None)
    updated = apply_ops(draft, [SetOp(op="set", path="merchant_name", value="Fake Mart")])
    assert updated.merchant_name == "Fake Mart"
    assert draft.merchant_name is None  # original untouched


def test_apply_set_item_field() -> None:
    draft = _draft(items=[Item(name="a", price=None)])
    updated = apply_ops(draft, [SetOp(op="set", path="items[0].price", value=3.49)])
    assert updated.items[0].price == 3.49


def test_apply_set_total_marks_source_as_user() -> None:
    draft = _draft(total=None, total_source=None)
    updated = apply_ops(draft, [SetOp(op="set", path="total", value=42.1)])
    assert updated.total == 42.1
    assert updated.total_source == "user"


def test_apply_add_item() -> None:
    draft = _draft(items=[])
    updated = apply_ops(
        draft, [AddItemOp(op="add_item", value=AddItemValue(name="Eggs", price=4.99))]
    )
    assert updated.items == [Item(name="Eggs", price=4.99)]


def test_apply_remove_item() -> None:
    draft = _draft(items=[Item(name="a", price=1.0), Item(name="b", price=2.0)])
    updated = apply_ops(draft, [RemoveItemOp(op="remove_item", index=0)])
    assert updated.items == [Item(name="b", price=2.0)]


def test_apply_ops_in_order() -> None:
    draft = _draft(items=[Item(name="a", price=1.0)])
    updated = apply_ops(
        draft,
        [
            AddItemOp(op="add_item", value=AddItemValue(name="b", price=2.0)),
            RemoveItemOp(op="remove_item", index=0),
        ],
    )
    assert updated.items == [Item(name="b", price=2.0)]


# --- clearing a total override on a relevant field change (spec 8.1) --------


def _overridden_draft(**kwargs: object) -> Draft:
    from receipt_parser_backend.receipts.models import TotalCheck

    return _draft(
        total_check=TotalCheck(
            status="user_override", item_sum=1.0, expected_total=1.0, difference=9.0
        ),
        notes=["Total was set by the user, not extracted. ..."],
        **kwargs,
    )


def test_setting_an_item_price_clears_the_override() -> None:
    draft = _overridden_draft(items=[Item(name="a", price=None)])
    updated = apply_ops(draft, [SetOp(op="set", path="items[0].price", value=5.0)])
    assert updated.total_check is None
    assert updated.notes == []


def test_setting_discounts_clears_the_override() -> None:
    draft = _overridden_draft()
    updated = apply_ops(draft, [SetOp(op="set", path="discounts", value=1.0)])
    assert updated.total_check is None
    assert updated.notes == []


def test_setting_tax_clears_the_override() -> None:
    draft = _overridden_draft()
    updated = apply_ops(draft, [SetOp(op="set", path="tax", value=1.0)])
    assert updated.total_check is None
    assert updated.notes == []


def test_setting_total_clears_the_previous_override() -> None:
    draft = _overridden_draft()
    updated = apply_ops(draft, [SetOp(op="set", path="total", value=42.0)])
    assert updated.total_check is None
    assert updated.notes == []


def test_adding_an_item_clears_the_override() -> None:
    draft = _overridden_draft(items=[])
    updated = apply_ops(draft, [AddItemOp(op="add_item", value=AddItemValue(name="x", price=1.0))])
    assert updated.total_check is None
    assert updated.notes == []


def test_removing_an_item_clears_the_override() -> None:
    draft = _overridden_draft(items=[Item(name="a", price=1.0)])
    updated = apply_ops(draft, [RemoveItemOp(op="remove_item", index=0)])
    assert updated.total_check is None
    assert updated.notes == []


def test_setting_an_unrelated_field_does_not_clear_the_override() -> None:
    draft = _overridden_draft()
    updated = apply_ops(draft, [SetOp(op="set", path="merchant_name", value="Fake Mart")])
    assert updated.total_check is not None
    assert updated.total_check.status == "user_override"
    assert updated.notes != []


# --- category (529 report field) ---------------------------------------------


def test_category_room_is_valid() -> None:
    output = InterpreterOutput(intent="edit", ops=[SetOp(op="set", path="category", value="room")])
    result = validate_interpreter_output(
        output, state=SessionState.AWAITING_CONFIRMATION, active_question=None, item_count=0
    )
    assert result.intent == "edit"


def test_category_board_is_valid() -> None:
    output = InterpreterOutput(intent="edit", ops=[SetOp(op="set", path="category", value="board")])
    result = validate_interpreter_output(
        output, state=SessionState.AWAITING_CONFIRMATION, active_question=None, item_count=0
    )
    assert result.intent == "edit"


def test_category_is_case_insensitive() -> None:
    output = InterpreterOutput(intent="edit", ops=[SetOp(op="set", path="category", value="ROOM")])
    result = validate_interpreter_output(
        output, state=SessionState.AWAITING_CONFIRMATION, active_question=None, item_count=0
    )
    assert result.intent == "edit"


def test_category_rejects_anything_other_than_room_or_board() -> None:
    output = InterpreterOutput(
        intent="edit", ops=[SetOp(op="set", path="category", value="restaurant")]
    )
    result = validate_interpreter_output(
        output, state=SessionState.AWAITING_CONFIRMATION, active_question=None, item_count=0
    )
    assert result.intent == "unclear"


def test_apply_set_category() -> None:
    draft = _draft(category=None)
    updated = apply_ops(draft, [SetOp(op="set", path="category", value="room")])
    assert updated.category == "room"
    assert draft.category is None  # original untouched


def test_apply_set_category_normalizes_case() -> None:
    draft = _draft(category=None)
    updated = apply_ops(draft, [SetOp(op="set", path="category", value="Board")])
    assert updated.category == "board"
