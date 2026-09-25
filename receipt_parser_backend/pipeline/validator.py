"""Validator (spec Section 8, Step 5).

Re-run after normalization and after every draft change, per spec. Notes
(spec 8.1) are never written here: they're set explicitly by
:mod:`receipt_parser_backend.pipeline.engine` at the moment a total override
happens, and cleared by :mod:`receipt_parser_backend.pipeline.ops` the moment
a relevant field changes again - this module only ever reads
``draft.total_check`` to decide whether an existing override still applies.
"""

from __future__ import annotations

from dataclasses import dataclass

from receipt_parser_backend.countries import CountryProfile
from receipt_parser_backend.pipeline.questions import (
    MISSING_DATE,
    MISSING_TOTAL,
    TOTAL_MISMATCH,
    missing_item_price_question_id,
)
from receipt_parser_backend.receipts.models import Draft, TotalCheck


@dataclass(frozen=True)
class ValidationResult:
    refused: bool
    question_queue: list[str]


def compute_total_check(draft: Draft, profile: CountryProfile) -> TotalCheck:
    """Pure Step 5.3 arithmetic: item sum, expected total, and the difference.

    ``status`` is either ``match`` or ``mismatch`` - never ``user_override``,
    which only ever comes from an explicit user action (spec 8.1), not from
    this recompute. Callers that want to preserve an existing override decide
    that themselves.
    """

    assert draft.total is not None
    item_sum = sum(item.price for item in draft.items if item.price is not None)
    discounts = draft.discounts or 0.0
    tax = draft.tax or 0.0
    expected_total = (
        item_sum - discounts + tax if profile.tax_model == "additive" else item_sum - discounts
    )
    difference = abs(draft.total - expected_total)
    status = "match" if difference <= profile.total_tolerance else "mismatch"
    return TotalCheck(
        status=status, item_sum=item_sum, expected_total=expected_total, difference=difference
    )


def validate_and_build_questions(draft: Draft, profile: CountryProfile) -> ValidationResult:
    """Return the refusal flag and question queue for ``draft`` (spec Step 5)."""

    if (
        draft.date is None
        and not draft.items
        and draft.total is None
        and draft.merchant_name is None
    ):
        return ValidationResult(refused=True, question_queue=[])

    queue: list[str] = []
    if draft.date is None:
        queue.append(MISSING_DATE)
    for index, item in enumerate(draft.items):
        if item.price is None:
            queue.append(missing_item_price_question_id(index))
    if draft.total is None:
        queue.append(MISSING_TOTAL)

    if draft.total is not None and all(item.price is not None for item in draft.items):
        if _run_total_check(draft, profile):
            queue.append(TOTAL_MISMATCH)
    else:
        draft.total_check = None

    return ValidationResult(refused=False, question_queue=queue)


def _run_total_check(draft: Draft, profile: CountryProfile) -> bool:
    """Update ``draft.total_check`` in place. Returns True to queue ``total_mismatch``."""

    check = compute_total_check(draft, profile)
    if check.status == "match":
        draft.total_check = check
        return False

    if draft.total_check is not None and draft.total_check.status == "user_override":
        # Spec 5.3: already overridden - accept it, no question, just refresh the numbers.
        draft.total_check = TotalCheck(
            status="user_override",
            item_sum=check.item_sum,
            expected_total=check.expected_total,
            difference=check.difference,
        )
        return False

    draft.total_check = check  # status == "mismatch"
    return True
