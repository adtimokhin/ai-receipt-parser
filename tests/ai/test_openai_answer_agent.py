"""Real Q&A agent (third AI touchpoint, see ai/answer.py) backed by OpenAI."""

from __future__ import annotations

import json

import httpx2
import pytest
from openai import AsyncOpenAI, DefaultAsyncHttpxClient

from receipt_parser_backend.ai.openai_answer_agent import FALLBACK_ANSWER, OpenAIAnswerAgent
from receipt_parser_backend.llm.openai import client as openai_client_mod
from receipt_parser_backend.receipts.models import Draft, Item

_DRAFT = Draft(
    merchant_name="Fake Mart",
    currency="USD",
    date="2026-01-15",
    total=10.79,
    items=[Item(name="Milk", price=5.49), Item(name="Bread", price=4.30)],
)


def _chat_completion(content: str | None) -> dict[str, object]:
    return {
        "id": "chatcmpl-test",
        "object": "chat.completion",
        "created": 0,
        "model": "gpt-4o-mini",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }


def _install(
    monkeypatch: pytest.MonkeyPatch,
    *,
    content: str | None = "Here's your answer.",
    status_code: int = 200,
    captured_requests: list[httpx2.Request] | None = None,
) -> None:
    body = _chat_completion(content)

    def _handler(request: httpx2.Request) -> httpx2.Response:
        if captured_requests is not None:
            captured_requests.append(request)
        return httpx2.Response(status_code, json=body)

    client = AsyncOpenAI(
        api_key="test-key",
        http_client=DefaultAsyncHttpxClient(transport=httpx2.MockTransport(_handler)),
        max_retries=0,
    )
    monkeypatch.setattr(openai_client_mod, "_client", client)


async def test_returns_the_models_answer(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch, content="You spent 10.79 USD in total.")
    result = await OpenAIAnswerAgent().answer(
        draft=_DRAFT, question="what's the total?", country_instructions="The user is in the US."
    )
    assert result == "You spent 10.79 USD in total."


async def test_empty_content_becomes_the_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch, content=None)
    result = await OpenAIAnswerAgent().answer(
        draft=_DRAFT, question="what's the total?", country_instructions=""
    )
    assert result == FALLBACK_ANSWER


async def test_api_error_becomes_the_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch, status_code=500, content="irrelevant")
    result = await OpenAIAnswerAgent().answer(
        draft=_DRAFT, question="what's the total?", country_instructions=""
    )
    assert result == FALLBACK_ANSWER


async def test_prompt_includes_the_indexed_items_and_question(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[httpx2.Request] = []
    _install(monkeypatch, captured_requests=captured)

    await OpenAIAnswerAgent().answer(
        draft=_DRAFT,
        question="how much did the bread cost?",
        country_instructions="The user is in the US.",
    )

    payload = json.loads(captured[0].content)
    user_message = next(m["content"] for m in payload["messages"] if m["role"] == "user")
    assert "0: 'Milk' - 5.49 USD" in user_message
    assert "1: 'Bread' - 4.3 USD" in user_message
    assert "how much did the bread cost?" in user_message
    assert "The user is in the US." in user_message
