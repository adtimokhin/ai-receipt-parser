"""Validator (spec Step 5): refusal check, required-field gaps, and the total check."""

from __future__ import annotations

from receipt_parser_backend.countries.registry import FR, US
from receipt_parser_backend.pipeline.questions import (
    MISSING_DATE,
    MISSING_TOTAL,
    TOTAL_MISMATCH,
    missing_item_price_question_id,
)
from receipt_parser_backend.pipeline.validator import (
    compute_total_check,
    validate_and_build_questions,
)
from receipt_parser_backend.receipts.models import Draft, Item, TotalCheck


def test_refuses_when_date_items_total_and_merchant_all_missing() -> None:
    draft = Draft(currency="USD")
    result = validate_and_build_questions(draft, US)
    assert result.refused is True
    assert result.question_queue == []


def test_not_refused_when_only_merchant_is_present() -> None:
    draft = Draft(currency="USD", merchant_name="Fake Mart")
    result = validate_and_build_questions(draft, US)
    assert result.refused is False


def test_no_gaps_when_everything_required_is_present_and_total_matches() -> None:
    draft = Draft(
        currency="USD",
        date="2026-01-15",
        total=10.0,
        items=[Item(name="a", price=10.0)],
    )
    result = validate_and_build_questions(draft, US)
    assert result.refused is False
    assert result.question_queue == []


def test_missing_date_is_queued() -> None:
    draft = Draft(currency="USD", date=None, total=10.0, items=[Item(name="a", price=10.0)])
    result = validate_and_build_questions(draft, US)
    assert MISSING_DATE in result.question_queue


def test_missing_total_is_queued() -> None:
    draft = Draft(currency="USD", date="2026-01-15", total=None, items=[Item(name="a", price=10.0)])
    result = validate_and_build_questions(draft, US)
    assert MISSING_TOTAL in result.question_queue


def test_missing_item_price_is_queued_per_item() -> None:
    draft = Draft(
        currency="USD",
        date="2026-01-15",
        total=10.0,
        items=[Item(name="a", price=None), Item(name="b", price=5.0), Item(name="c", price=None)],
    )
    result = validate_and_build_questions(draft, US)
    assert result.question_queue == [
        missing_item_price_question_id(0),
        missing_item_price_question_id(2),
    ]


def test_gaps_are_queued_in_date_items_total_order() -> None:
    draft = Draft(currency="USD", date=None, total=None, items=[Item(name="a", price=None)])
    result = validate_and_build_questions(draft, US)
    assert result.question_queue == [MISSING_DATE, missing_item_price_question_id(0), MISSING_TOTAL]


def test_total_check_is_not_run_until_total_and_all_item_prices_are_present() -> None:
    draft = Draft(currency="USD", date="2026-01-15", total=None, items=[Item(name="a", price=None)])
    validate_and_build_questions(draft, US)
    assert draft.total_check is None
    assert TOTAL_MISMATCH not in validate_and_build_questions(draft, US).question_queue


# --- total check arithmetic (spec 8, Step 5.3) ---------------------------------


def test_compute_total_check_additive_tax_model() -> None:
    draft = Draft(
        currency="USD", total=10.8, discounts=0.0, tax=0.8, items=[Item(name="a", price=10.0)]
    )
    check = compute_total_check(draft, US)
    assert check.status == "match"
    assert check.expected_total == 10.8


def test_compute_total_check_inclusive_tax_model_ignores_tax() -> None:
    draft = Draft(currency="EUR", total=10.0, tax=0.8, items=[Item(name="a", price=10.0)])
    check = compute_total_check(draft, FR)
    assert check.status == "match"
    assert check.expected_total == 10.0


def test_compute_total_check_subtracts_discounts() -> None:
    draft = Draft(currency="USD", total=9.0, discounts=1.0, items=[Item(name="a", price=10.0)])
    check = compute_total_check(draft, US)
    assert check.status == "match"
    assert check.expected_total == 9.0


def test_compute_total_check_within_tolerance_matches() -> None:
    draft = Draft(currency="USD", total=10.01, items=[Item(name="a", price=10.0)])
    check = compute_total_check(draft, US)  # tolerance is 0.02
    assert check.status == "match"


def test_compute_total_check_just_outside_tolerance_mismatches() -> None:
    draft = Draft(currency="USD", total=10.03, items=[Item(name="a", price=10.0)])
    check = compute_total_check(draft, US)
    assert check.status == "mismatch"


def test_total_mismatch_is_queued_for_a_real_mismatch() -> None:
    draft = Draft(currency="USD", date="2026-01-15", total=20.0, items=[Item(name="a", price=10.0)])
    result = validate_and_build_questions(draft, US)
    assert TOTAL_MISMATCH in result.question_queue
    assert draft.total_check is not None
    assert draft.total_check.status == "mismatch"


# --- override preservation (spec 5.3's "already user_override" branch) --------


def test_existing_override_is_preserved_and_not_re_queued() -> None:
    draft = Draft(
        currency="USD",
        date="2026-01-15",
        total=20.0,
        items=[Item(name="a", price=10.0)],
        total_check=TotalCheck(
            status="user_override", item_sum=10.0, expected_total=10.0, difference=10.0
        ),
    )
    result = validate_and_build_questions(draft, US)
    assert TOTAL_MISMATCH not in result.question_queue
    assert draft.total_check is not None
    assert draft.total_check.status == "user_override"


def test_existing_override_numbers_are_refreshed() -> None:
    draft = Draft(
        currency="USD",
        date="2026-01-15",
        total=20.0,
        items=[Item(name="a", price=10.0), Item(name="b", price=5.0)],
        total_check=TotalCheck(
            status="user_override", item_sum=10.0, expected_total=10.0, difference=10.0
        ),
    )
    validate_and_build_questions(draft, US)
    assert draft.total_check is not None
    assert draft.total_check.item_sum == 15.0


def test_override_does_not_survive_if_it_now_matches() -> None:
    draft = Draft(
        currency="USD",
        date="2026-01-15",
        total=10.0,
        items=[Item(name="a", price=10.0)],
        total_check=TotalCheck(
            status="user_override", item_sum=5.0, expected_total=5.0, difference=5.0
        ),
    )
    result = validate_and_build_questions(draft, US)
    assert draft.total_check is not None
    assert draft.total_check.status == "match"
    assert TOTAL_MISMATCH not in result.question_queue
