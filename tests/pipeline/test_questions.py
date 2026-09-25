"""Question templates (spec Step 5 table)."""

from __future__ import annotations

import pytest

from receipt_parser_backend.pipeline.questions import (
    MISSING_DATE,
    MISSING_TOTAL,
    missing_item_price_question_id,
    parse_question_id,
    question_text,
)
from receipt_parser_backend.receipts.models import Draft, Item


def test_missing_date_question_text() -> None:
    draft = Draft(currency="USD")
    assert "date" in question_text(MISSING_DATE, draft).lower()


def test_missing_total_question_text() -> None:
    draft = Draft(currency="USD")
    assert "total" in question_text(MISSING_TOTAL, draft).lower()


def test_missing_item_price_question_text_uses_item_name() -> None:
    draft = Draft(currency="USD", items=[Item(name="Baguette", price=None)])
    text = question_text(missing_item_price_question_id(0), draft)
    assert "Baguette" in text


def test_missing_item_price_question_text_falls_back_when_name_is_missing() -> None:
    draft = Draft(currency="USD", items=[Item(name=None, price=None)])
    text = question_text(missing_item_price_question_id(0), draft)
    assert "an item" in text


def test_parse_question_id_splits_item_index() -> None:
    assert parse_question_id(missing_item_price_question_id(3)) == ("missing_item_price", 3)


def test_parse_question_id_passes_through_plain_ids() -> None:
    assert parse_question_id(MISSING_DATE) == (MISSING_DATE, None)


def test_question_text_raises_for_unknown_id() -> None:
    with pytest.raises(ValueError, match="unknown question id"):
        question_text("not_a_real_question", Draft(currency="USD"))
