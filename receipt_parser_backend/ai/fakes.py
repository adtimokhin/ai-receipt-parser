"""In-memory stand-ins for the AI touchpoints (spec 9.1, 9.2, and the answer agent).

The app now uses the real ``OpenAIInterpreter`` (Milestone 5),
``LlamaExtractExtractor`` (Milestone 6), and ``OpenAIAnswerAgent`` behind the
same ``InterpreterPort``/``ExtractorPort``/``AnswerPort`` contracts. The fakes
here remain the test doubles for everything that shouldn't depend on a real
API call.
"""

from __future__ import annotations

import uuid

from receipt_parser_backend.ai.extraction import ExtractionFailed, RawExtraction, RawExtractionItem
from receipt_parser_backend.ai.interpreter import InterpreterOutput
from receipt_parser_backend.countries import CountryProfile
from receipt_parser_backend.receipts.models import Draft, SessionState

DEFAULT_RESULT = RawExtraction(
    merchant_name="Fake Mart",
    currency=None,
    # Day <= 12 so this parses to a real date under either MM/DD or DD/MM.
    date="01/05/2026",
    time="12:00",
    items=[RawExtractionItem(name="Sample Item", price=9.99)],
    discounts=0.0,
    tax=0.8,
    total=10.79,
)


class FakeExtractor:
    """Returns a fixed, configurable extraction result for every submission.

    Tests construct their own instance with a custom ``result`` (``None`` to
    simulate "nothing extracted", or ``fail=True`` to simulate a failed job)
    to exercise gaps, refusals, and failures deterministically.
    """

    def __init__(
        self, result: RawExtraction | None = DEFAULT_RESULT, *, fail: bool = False
    ) -> None:
        self.result = result
        self.fail = fail
        self.submitted: list[tuple[bytes, str]] = []

    async def submit(self, file_bytes: bytes, mime_type: str, profile: CountryProfile) -> str:
        self.submitted.append((file_bytes, mime_type))
        return f"fake-job-{uuid.uuid4().hex[:8]}"

    async def fetch_result(self, job_id: str) -> RawExtraction | None:
        if self.fail:
            raise ExtractionFailed(f"fake extraction failure for {job_id}")
        return self.result


class FakeInterpreter:
    """Returns a fixed, configurable interpreter output for every reply.

    Defaults to ``unclear`` (the safe default for an unconfigured fake); tests
    set ``response`` to whatever ``InterpreterOutput`` they want to exercise.
    """

    def __init__(self, response: InterpreterOutput | None = None) -> None:
        self.response = response or InterpreterOutput(intent="unclear")
        self.calls: list[str] = []

    async def interpret(
        self,
        *,
        state: SessionState,
        draft: Draft,
        active_question: str | None,
        interpreter_prompt: str,
        user_text: str,
    ) -> InterpreterOutput:
        self.calls.append(user_text)
        return self.response


class FakeAnswerAgent:
    """Returns a fixed, configurable answer for every question.

    Defaults to a canned sentence; tests set ``response`` to whatever text
    they want to assert on.
    """

    def __init__(self, response: str = "That's a fake answer.") -> None:
        self.response = response
        self.calls: list[str] = []

    async def answer(self, *, draft: Draft, question: str, country_instructions: str) -> str:
        self.calls.append(question)
        return self.response
