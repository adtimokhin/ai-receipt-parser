"""Real Q&A agent (the third AI touchpoint - see ``ai/answer.py``), backed by OpenAI.

Plain chat completion, not structured outputs: the output is prose for a
human to read, not data another part of the system parses or applies.
"""

from __future__ import annotations

import structlog
from openai import APIConnectionError, RateLimitError
from openai.types.chat import ChatCompletionMessageParam
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from receipt_parser_backend.ai.draft_context import render_draft_for_prompt
from receipt_parser_backend.config import get_settings
from receipt_parser_backend.llm.openai.client import get_client
from receipt_parser_backend.receipts.models import Draft

logger = structlog.get_logger(__name__)

_SYSTEM_PROMPT = """\
You answer a user's question about a single receipt, using only the data \
given below - never invent a number, item, or fact that isn't there. If the \
data doesn't answer the question (e.g. a field is still unknown/null), say \
so plainly rather than guessing.

Be concise - a sentence or two, not a report. You are not making any change \
to the receipt here, only answering a question about it; if the user is \
actually asking you to change something, briefly say so and tell them to \
state the change directly (e.g. "say what the correct price is and I'll \
update it") rather than attempting an edit yourself - you have no way to \
apply one from here.
"""

FALLBACK_ANSWER = "Sorry, I couldn't look that up just now - try asking again."


class OpenAIAnswerAgent:
    """The real :class:`~receipt_parser_backend.ai.answer.AnswerPort`."""

    async def answer(self, *, draft: Draft, question: str, country_instructions: str) -> str:
        try:
            return await self._call(draft, question, country_instructions)
        except Exception as exc:
            # Mirrors OpenAIInterpreter's reasoning: any failure here - network,
            # rate limits, a safety refusal - must degrade to a plain fallback
            # reply, never bubble up and fail the webhook request.
            logger.warning("answer_agent.call_failed", error=repr(exc))
            return FALLBACK_ANSWER

    @retry(
        reraise=True,
        stop=stop_after_attempt(2),
        wait=wait_exponential(multiplier=0.5, max=4),
        retry=retry_if_exception_type((APIConnectionError, RateLimitError)),
    )
    async def _call(self, draft: Draft, question: str, country_instructions: str) -> str:
        settings = get_settings()
        messages: list[ChatCompletionMessageParam] = [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": _user_message(draft, question, country_instructions)},
        ]
        completion = await get_client().chat.completions.create(
            model=settings.llm_openai_model,
            temperature=0,
            messages=messages,
        )
        content = completion.choices[0].message.content
        answer = content.strip() if content else ""
        if not answer:
            logger.info("answer_agent.empty_response")
            return FALLBACK_ANSWER
        return answer


def _user_message(draft: Draft, question: str, country_instructions: str) -> str:
    return (
        f"Country formatting conventions: {country_instructions}\n"
        f"Receipt data:\n{render_draft_for_prompt(draft)}\n"
        f"Question: {question}"
    )
