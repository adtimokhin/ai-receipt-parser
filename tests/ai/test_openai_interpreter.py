"""Real reply interpreter (spec 9.2), backed by OpenAI structured outputs."""

from __future__ import annotations

import json

import httpx2
import pytest
from openai import AsyncOpenAI, DefaultAsyncHttpxClient

from receipt_parser_backend.ai.interpreter import InterpreterOutput
from receipt_parser_backend.ai.openai_interpreter import OpenAIInterpreter
from receipt_parser_backend.llm.openai import client as openai_client_mod
from receipt_parser_backend.receipts.models import Draft, Item, SessionState

_DRAFT = Draft(currency="USD", date=None, total=10.0, items=[Item(name="a", price=10.0)])


def _chat_completion(message: dict[str, object]) -> dict[str, object]:
    return {
        "id": "chatcmpl-test",
        "object": "chat.completion",
        "created": 0,
        "model": "gpt-4o-mini",
        "choices": [
            {"index": 0, "message": {"role": "assistant", **message}, "finish_reason": "stop"}
        ],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }


def _install(
    monkeypatch: pytest.MonkeyPatch,
    *,
    message: dict[str, object] | None = None,
    status_code: int = 200,
    captured_requests: list[httpx2.Request] | None = None,
) -> None:
    body = _chat_completion(message or {"content": json.dumps({"intent": "unclear", "ops": []})})

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


async def _interpret(**overrides: object) -> InterpreterOutput:
    defaults: dict[str, object] = {
        "state": SessionState.AWAITING_ANSWERS,
        "draft": _DRAFT,
        "active_question": "missing_date",
        "interpreter_prompt": "The user is in the United States.",
        "user_text": "hello",
    }
    defaults.update(overrides)
    return await OpenAIInterpreter().interpret(**defaults)  # type: ignore[arg-type]


async def test_valid_confirm_response_is_parsed(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch, message={"content": json.dumps({"intent": "confirm", "ops": []})})
    result = await _interpret(state=SessionState.AWAITING_CONFIRMATION, active_question=None)
    assert result.intent == "confirm"
    assert result.ops == []


async def test_valid_answer_with_set_op_is_parsed(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(
        monkeypatch,
        message={
            "content": json.dumps(
                {"intent": "answer", "ops": [{"op": "set", "path": "date", "value": "2026-01-15"}]}
            )
        },
    )
    result = await _interpret()
    assert result.intent == "answer"
    assert len(result.ops) == 1
    op = result.ops[0]
    assert op.op == "set"
    assert op.path == "date"
    assert op.value == "2026-01-15"


async def test_valid_add_item_op_is_parsed(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(
        monkeypatch,
        message={
            "content": json.dumps(
                {
                    "intent": "edit",
                    "ops": [{"op": "add_item", "value": {"name": "Eggs", "price": 4.99}}],
                }
            )
        },
    )
    result = await _interpret(state=SessionState.AWAITING_CONFIRMATION, active_question=None)
    assert result.ops[0].op == "add_item"


async def test_malformed_json_content_becomes_unclear(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch, message={"content": "not valid json at all"})
    result = await _interpret()
    assert result.intent == "unclear"
    assert result.ops == []


async def test_refusal_becomes_unclear(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch, message={"content": None, "refusal": "I can't help with that."})
    result = await _interpret()
    assert result.intent == "unclear"


async def test_api_error_status_becomes_unclear(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch, status_code=500, message={"content": "irrelevant"})
    result = await _interpret()
    assert result.intent == "unclear"


async def test_prompt_carries_state_question_and_country_instructions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[httpx2.Request] = []
    _install(monkeypatch, captured_requests=captured)

    await _interpret(
        state=SessionState.AWAITING_ANSWERS,
        active_question="missing_date",
        interpreter_prompt="The user is in France. Numbers may use a comma.",
        user_text="le 15 janvier",
    )

    assert len(captured) == 1
    payload = json.loads(captured[0].content)
    user_message = next(m["content"] for m in payload["messages"] if m["role"] == "user")
    assert "AWAITING_ANSWERS" in user_message
    assert "missing_date" in user_message
    assert "France" in user_message
    assert "le 15 janvier" in user_message
