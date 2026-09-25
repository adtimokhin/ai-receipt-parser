"""Real reply interpreter (spec 9.2), backed by OpenAI structured outputs.

Uses ``chat.completions.parse`` with
:class:`~receipt_parser_backend.ai.interpreter.InterpreterOutput` as the
``response_format``: the SDK converts that Pydantic model (discriminated
union and all) straight into a strict JSON schema, so the model can only ever
return a shape that already matches the port's contract - that's what the
field descriptions on that model are actually for. Section 9.2's own
allowlist/type/bounds validation still runs afterward in
:mod:`receipt_parser_backend.pipeline.ops`; this class only owns getting *a*
well-typed answer out of the model, never whether that answer is safe to
apply.
"""

from __future__ import annotations

import structlog
from openai import APIConnectionError, RateLimitError
from openai.types.chat import ChatCompletionMessageParam
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from receipt_parser_backend.ai.draft_context import render_draft_for_prompt
from receipt_parser_backend.ai.interpreter import InterpreterOutput
from receipt_parser_backend.config import get_settings
from receipt_parser_backend.llm.openai.client import get_client
from receipt_parser_backend.pipeline.questions import parse_question_id, question_text
from receipt_parser_backend.receipts.models import Draft, SessionState

logger = structlog.get_logger(__name__)

_SYSTEM_PROMPT = """\
You interpret a user's free-text reply about a receipt draft into a \
structured intent and a list of edit operations. You never write any reply \
text yourself - the user only ever sees text from the app's own templates.

Allowed intents depend on the current state:
- AWAITING_ANSWERS: "answer" (the user is answering the active question, or \
otherwise supplying/correcting a field), "accept_total" (only when the \
active question is total_mismatch, and the user says the total shown is \
correct as-is despite not matching the items), "query" (see below), \
"unclear" (anything that doesn't clearly fit either).
- AWAITING_CONFIRMATION: "confirm" (the user accepts the receipt as shown), \
"edit" (the user wants to change a field), "query" (see below), "unclear" \
(anything that doesn't clearly fit either).
If you are not confident, use "unclear" rather than guessing.

Use "query" when the user is asking a question about the receipt's current \
data rather than trying to change or confirm anything - e.g. "what's the \
total", "how much did I spend on X", "is there a discount here", "what was \
the second item". "query" never carries ops; a separate step answers it \
directly from the current draft. If a message is ambiguous between "explain \
this to me" and "change this", prefer "query" only when there's no concrete \
new value being given - "why is the total wrong" is a query, "the total is \
actually $12" is an answer/edit.

If the active question asks for a missing item's price and the user instead \
says that item isn't real - "discard it", "remove it", "delete that line", \
"that's not an item", calling it a duplicate, a promo line, or a fee that \
shouldn't be counted separately - that is still intent "answer", with a \
remove_item op for that item. Do not treat it as unclear just because no \
price was given.

The draft's items are listed below as "index: name - price", using the \
receipt's own printed (sometimes abbreviated or truncated) names. When the \
user refers to an item, match it to the closest one in that list by name - \
it will often be reworded, shortened, or missing a leading code like "T " - \
and use *that* item's exact index in any op. Answering a total_mismatch \
question often means correcting several items at once (e.g. three separate \
"X was $Y" corrections in one message, or naming one item to remove): return \
one op per correction, all in the same ops list, not just the first one.

An op is one of:
- {"op": "set", "path": <field path>, "value": <new value>} - path must be \
one of: merchant_name, currency, date, time, items[n].name, items[n].price, \
discounts, tax, total (n is the item's index from the list below).
- {"op": "add_item", "value": {"name": ..., "price": ...}}
- {"op": "remove_item", "index": <the item's index from the list below>}

Values must already be in canonical form, using the country instructions \
below to parse the user's own formatting: dates as ISO "YYYY-MM-DD", times \
as 24-hour "HH:MM", currency as an uppercase ISO 4217 code, and prices/\
discounts/tax/total as plain non-negative numbers. "confirm", "accept_total", \
and "unclear" never carry ops.
"""


class OpenAIInterpreter:
    """The real :class:`~receipt_parser_backend.ai.interpreter.InterpreterPort`."""

    async def interpret(
        self,
        *,
        state: SessionState,
        draft: Draft,
        active_question: str | None,
        interpreter_prompt: str,
        user_text: str,
    ) -> InterpreterOutput:
        try:
            return await self._call(state, draft, active_question, interpreter_prompt, user_text)
        except Exception as exc:
            # Spec Section 10: "Interpreter call failure -> Treat as unclear,
            # re-ask." Anything that goes wrong here - network, rate limits,
            # a safety refusal, an unparseable response - must degrade to a
            # re-ask, never bubble up and fail the webhook request.
            logger.warning("interpreter.call_failed", error=repr(exc))
            return InterpreterOutput(intent="unclear")

    @retry(
        reraise=True,
        stop=stop_after_attempt(2),
        wait=wait_exponential(multiplier=0.5, max=4),
        retry=retry_if_exception_type((APIConnectionError, RateLimitError)),
    )
    async def _call(
        self,
        state: SessionState,
        draft: Draft,
        active_question: str | None,
        interpreter_prompt: str,
        user_text: str,
    ) -> InterpreterOutput:
        settings = get_settings()
        messages: list[ChatCompletionMessageParam] = [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {
                "role": "user",
                "content": _user_message(
                    state, draft, active_question, interpreter_prompt, user_text
                ),
            },
        ]
        completion = await get_client().chat.completions.parse(
            model=settings.llm_openai_model,
            temperature=0,
            messages=messages,
            response_format=InterpreterOutput,
        )
        message = completion.choices[0].message
        if message.refusal or message.parsed is None:
            logger.info(
                "interpreter.no_parsed_output",
                refusal=message.refusal,
                content=message.content,
            )
            return InterpreterOutput(intent="unclear")
        return message.parsed


def _user_message(
    state: SessionState,
    draft: Draft,
    active_question: str | None,
    interpreter_prompt: str,
    user_text: str,
) -> str:
    return (
        f"State: {state.value}\n"
        f"Active question: {_render_active_question(active_question, draft)}\n"
        f"Country instructions: {interpreter_prompt}\n"
        f"Current draft:\n{render_draft_for_prompt(draft)}\n"
        f"User's reply: {user_text}"
    )


def _render_active_question(active_question: str | None, draft: Draft) -> str:
    """The question's own id plus the exact text the user was shown.

    For a missing-item-price question, also names the item and its index
    explicitly, so the model doesn't have to infer "which item" by counting
    through the draft JSON itself - that's what let a "discard it" reply
    silently fail before (spec 9.2's own id, e.g. "missing_item_price:4",
    carried none of that).
    """

    if active_question is None:
        return "none"

    rendered = question_text(active_question, draft)
    _, item_index = parse_question_id(active_question)
    if item_index is not None:
        item_name = draft.items[item_index].name or "an item"
        rendered += (
            f' [Specifically about the item at index {item_index} ("{item_name}"). If the '
            "user says it isn't a real item, use remove_item with index "
            f"{item_index} instead of a price.]"
        )
    return f'{active_question} - "{rendered}"'
