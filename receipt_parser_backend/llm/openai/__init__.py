"""OpenAI client overlay (D-002).

Async :class:`~openai.AsyncOpenAI` bound to the app lifespan. Used by the
reply interpreter (spec 9.2), added in Milestone 5.

The client base URL is ``APP_LLM_OPENAI_BASE_URL`` (falls back to the SDK's
``OPENAI_BASE_URL``); point it at a local fake for offline tests (D-013).
"""

from receipt_parser_backend.llm.openai.client import close_client, get_client, init_client

__all__ = ["close_client", "get_client", "init_client"]
