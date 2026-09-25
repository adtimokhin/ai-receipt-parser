"""Extraction port (spec Section 9.1) - the first of the two AI touchpoints.

``RawExtraction`` is the untrusted shape LlamaExtract hands back: every field
description below is written for the model, not just for humans reading this
file, because it gets serialized straight into the ``data_schema`` LlamaExtract
uses to guide extraction (Milestone 6). Getting a field's description wrong is
getting the model's behavior wrong, not just the documentation.

Nothing here is normalized or trusted - the normalizer (Milestone 4, spec Step
4) is the guardrail that turns this into a :class:`~receipt_parser_backend.receipts.models.Draft`.
"""

from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel, Field

from receipt_parser_backend.countries import CountryProfile

# Spec Section 11 decision 5: accepted file types, mapped to a filename
# extension. Shared between intake validation (engine.py) and the real
# extractor (llamaextract_extractor.py), which needs a hinted filename.
ALLOWED_MIME_TYPES: dict[str, str] = {
    "application/pdf": "pdf",
    "image/jpeg": "jpg",
    "image/png": "png",
}


class RawExtractionItem(BaseModel):
    """One line item as extracted, before normalization."""

    name: str | None = Field(
        default=None,
        description=(
            "The item's description exactly as printed on the receipt. Null if "
            "illegible or the line couldn't be identified as a purchased item."
        ),
    )
    price: float | str | None = Field(
        default=None,
        description=(
            "The item's own price as printed - never a running subtotal. A "
            "number when the format is unambiguous; a numeral string when the "
            "receipt's own formatting (e.g. a decimal comma, a thousands "
            "separator) needs country-aware parsing before it's a number. Null "
            "if illegible - never guessed."
        ),
    )


class RawExtraction(BaseModel):
    """Extraction output schema (spec 9.1). Untrusted until normalized (Step 4)."""

    merchant_name: str | None = Field(
        default=None,
        description=(
            "The store or business name printed on the receipt. Null if illegible or not printed."
        ),
    )
    currency: str | None = Field(
        default=None,
        description=(
            "The currency as printed - a symbol, code, or word, not yet "
            "normalized to an ISO 4217 code. Null if it cannot be inferred from "
            "the receipt; the caller falls back to the country's default currency."
        ),
    )
    date: str | None = Field(
        default=None,
        description=(
            "The purchase date exactly as printed, in the receipt's own format "
            "(see the country-specific instructions for which format to expect). "
            "Not yet parsed to ISO 8601. Null if unreadable - never guessed."
        ),
    )
    time: str | None = Field(
        default=None,
        description="The purchase time exactly as printed. Null if not printed or unreadable.",
    )
    items: list[RawExtractionItem] = Field(
        default_factory=list,
        description=(
            "Every purchased line item, in the order printed. Excludes "
            "payment/tender lines (e.g. card, cash, change) - those are not items."
        ),
    )
    discounts: float | str | None = Field(
        default=None,
        description=(
            "The total discount amount, recorded as a positive number even "
            "though it reduces what was paid. Null if no discount line is present."
        ),
    )
    tax: float | str | None = Field(
        default=None,
        description=(
            "The tax or VAT amount as printed. For a country where prices "
            "already include tax, this is informational only. Null if not shown "
            "as its own line."
        ),
    )
    total: float | str | None = Field(
        default=None,
        description=(
            "The final amount actually paid - never a subtotal before tax or "
            "discounts. Null if it cannot be determined - never guessed."
        ),
    )
    category: str | None = Field(
        default=None,
        description=(
            "Your best guess at whether this receipt is a qualified IRS Section "
            "529 education expense, based on the merchant name and the items "
            "purchased (this is inferred - it is not printed on the receipt). "
            "Exactly 'room' for rent, a dorm, or apartment/housing charges. "
            "Exactly 'board' for groceries or a meal plan meant for personal "
            "meals - a grocery store or supermarket is 'board'. Null for a "
            "restaurant, cafe, bar, or any alcohol purchase - those do NOT "
            "qualify even though they involve food. Null for anything else "
            "that isn't clearly rent or groceries/a meal plan."
        ),
    )


class ExtractionFailed(Exception):
    """Raised by :meth:`ExtractorPort.fetch_result` when the job failed (spec Step 3.2)."""


class ExtractorPort(Protocol):
    """The extraction AI touchpoint (spec 9.1): submit a job, then poll it.

    Takes raw file bytes directly - matching spec 9.1's own "file in" framing.
    Downloading from Telegram and uploading the original to R2 are separate
    storage concerns the state machine (``pipeline/engine.py``) handles itself
    before calling this; the real implementation only owns the LlamaExtract
    call (including ``disable_cache``, spec design rule 6) and its polling.
    """

    async def submit(self, file_bytes: bytes, mime_type: str, profile: CountryProfile) -> str:
        """Submit ``file_bytes`` for extraction.

        Returns an opaque job id to pass to :meth:`fetch_result` later.
        """
        ...

    async def fetch_result(self, job_id: str) -> RawExtraction | None:
        """Return the finished result, or ``None`` if the job is still running.

        Raises :class:`ExtractionFailed` if the job failed.
        """
        ...
