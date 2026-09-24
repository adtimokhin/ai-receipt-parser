"""Proves the llm_openai overlay is wired into the running app (overlay-contract 7).

Runs offline: an httpx2 ``MockTransport`` returns canned Chat Completions JSON,
so the readiness check exercises the real wiring with no network and no real
API key. The reply interpreter (spec 9.2) lands on this client in Milestone 5.
"""

from __future__ import annotations

from openai import AsyncOpenAI


async def test_llm_openai_boots(openai_client: object) -> None:
    from receipt_parser_backend.health import check_llm_openai
    from receipt_parser_backend.lifespan import lifespan
    from receipt_parser_backend.llm.openai.client import get_client
    from receipt_parser_backend.main import app

    async with lifespan(app):
        client = getattr(app.state, "llm_openai", None)
        assert client is not None, "llm_openai client missing from app.state"
        assert isinstance(client, AsyncOpenAI)
        assert client is get_client()

        result = await check_llm_openai()
        assert result.healthy, result
