"""Domain models for sessions, user settings, and receipts (spec Section 4).

Pure data shapes only. The state machine (Milestone 3), normalizer/validator
(Milestone 4), and persistence (Milestone 6) build behavior on top of these;
nothing here owns pipeline logic. ``draft`` and ``raw_extraction`` stay as
untyped documents, matching the spec's own placeholder shape, until the
normalizer/validator milestone fixes what a draft actually looks like.
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


class Session(BaseModel):
    """One session per whitelisted user (spec 4.3)."""

    telegram_user_id: int
    state: SessionState = SessionState.IDLE
    country_code: str | None = None
    draft: Document = Field(default_factory=dict)
    raw_extraction: Document = Field(default_factory=dict)
    question_queue: list[str] = Field(default_factory=list)
    current_question: str | None = None
    extraction_job_id: str | None = None
    cancelled: bool = False
    r2_keys: R2Keys = Field(default_factory=R2Keys)
    updated_at: datetime


class Item(BaseModel):
    """A single line item on a receipt."""

    name: str | None = None
    price: float | None = None


class TotalCheck(BaseModel):
    """Result of the country-aware total check (spec 8, 8.1)."""

    status: Literal["match", "user_override"]
    item_sum: float
    expected_total: float
    difference: float


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
