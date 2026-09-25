"""Receipt Q&A port - a third AI touchpoint, on top of spec 9.1's extraction
and 9.2's reply interpreter.

This one is a deliberate exception to two of the spec's non-negotiable
design rules ("exactly two AI touchpoints", "no AI-written user messages"):
answering an open-ended question ("how much did I spend on X") requires the
AI to generate the sentence the user reads, which can't be validated the way
an edit op's field path or index bounds can be - there's no structural check
for "is this sentence factually correct". The blast radius is bounded by
this port being read-only by construction: a wrong answer can mislead the
user in one reply, but it can never corrupt the draft or the persisted
receipt, and the user can immediately re-ask or just state a correction
(which routes to the interpreter as a normal edit instead).
"""

from __future__ import annotations

from typing import Protocol

from receipt_parser_backend.receipts.models import Draft


class AnswerPort(Protocol):
    """Answers a free-text question about the current draft. Never mutates it."""

    async def answer(self, *, draft: Draft, question: str, country_instructions: str) -> str:
        """Return a natural-language answer to ``question`` about ``draft``."""
        ...
