"""Domain models for sessions, user settings, and receipts (spec Section 4).

Pure data shapes only; behavior lives in ``receipt_parser_backend.pipeline``
and ``receipt_parser_backend.sessions``. ``raw_extraction`` stays an untyped
document (it's the AI's own output, defined precisely in
``receipt_parser_backend.ai.extraction.RawExtraction``); ``Draft`` is the
typed, normalized shape the pipeline actually works with.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field

Document = dict[str, Any]


class SessionState(StrEnum):
    """States from spec Section 7."""

    IDLE = "IDLE"
    PROCESSING = "PROCESSING"
    AWAITING_ANSWERS = "AWAITING_ANSWERS"
    AWAITING_CONFIRMATION = "AWAITING_CONFIRMATION"


class UserSettings(BaseModel):
    """Per-user persistent settings (spec 4.2)."""

    telegram_user_id: int
    country_code: str
    updated_at: datetime


class R2Keys(BaseModel):
    """Blob storage keys for a session's uploaded files."""

    original: str | None = None
    preprocessed: str | None = None


class Item(BaseModel):
    """A single line item on a receipt."""

    name: str | None = None
    price: float | None = None


class TotalCheck(BaseModel):
    """Result of the country-aware total check (spec 8, 8.1).

    ``mismatch`` is an internal, unresolved state used only on a working
    ``Draft`` while the ``total_mismatch`` question is queued - it means the
    numbers don't reconcile and the user hasn't answered yet. A persisted
    :class:`Receipt` never carries it: by the time a draft reaches
    ``AWAITING_CONFIRMATION`` (and can be ``/confirm``-ed), every question
    including ``total_mismatch`` has been resolved to ``match`` or
    ``user_override``.
    """

    status: Literal["match", "user_override", "mismatch"]
    item_sum: float
    expected_total: float
    difference: float


class Draft(BaseModel):
    """The typed, normalized receipt-in-progress (spec Section 8, Step 4 output).

    Milestone 3's normalizer produces one of these directly from an
    already-clean fake extraction; Milestone 4 hardens the path from raw,
    country-formatted extraction text to this shape.
    """

    merchant_name: str | None = None
    currency: str
    date: str | None = None
    time: str | None = None
    items: list[Item] = Field(default_factory=list)
    discounts: float | None = None
    tax: float | None = None
    total: float | None = None
    total_source: Literal["extracted", "user"] | None = None
    total_check: TotalCheck | None = None
    notes: list[str] = Field(default_factory=list)


class Session(BaseModel):
    """One session per whitelisted user (spec 4.3)."""

    telegram_user_id: int
    state: SessionState = SessionState.IDLE
    country_code: str | None = None
    draft: Draft | None = None
    raw_extraction: Document = Field(default_factory=dict)
    question_queue: list[str] = Field(default_factory=list)
    current_question: str | None = None
    extraction_job_id: str | None = None
    cancelled: bool = False
    r2_keys: R2Keys = Field(default_factory=R2Keys)
    # Not part of spec 4.3; a minimal stand-in for the confirmation prompt
    # /undo requires, since Section 7 has no state to model it in (see
    # Milestone 3 deviations). Cleared on any input other than a repeated
    # /undo while it's set.
    pending_action: Literal["undo"] | None = None
    updated_at: datetime


class ReceiptFiles(BaseModel):
    """Blob storage keys retained on the final record."""

    original_r2_key: str
    preprocessed_r2_key: str | None = None


class Receipt(BaseModel):
    """A final, persisted receipt record (spec 4.4)."""

    id: str | None = Field(default=None, alias="_id")
    telegram_user_id: int
    country_code: str
    merchant_name: str | None = None
    currency: str
    date: str | None = None
    time: str | None = None
    items: list[Item] = Field(default_factory=list)
    discounts: float | None = None
    tax: float | None = None
    total: float | None = None
    total_source: Literal["extracted", "user"] | None = None
    total_check: TotalCheck | None = None
    notes: list[str] = Field(default_factory=list)
    files: ReceiptFiles
    raw_extraction: Document = Field(default_factory=dict)
    created_at: datetime


class ProcessedUpdate(BaseModel):
    """A deduped Telegram ``update_id`` (spec 4.5)."""

    update_id: int
    processed_at: datetime
