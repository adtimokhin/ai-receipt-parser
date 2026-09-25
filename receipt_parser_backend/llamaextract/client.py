"""Process-wide async LlamaCloud client, bound to the FastAPI lifespan."""

from __future__ import annotations

from llama_cloud import AsyncLlamaCloud

from receipt_parser_backend.config import get_settings

_client: AsyncLlamaCloud | None = None


def init_client() -> AsyncLlamaCloud:
    """Build the client from settings. Idempotent within a process."""

    global _client

    settings = get_settings()
    _client = AsyncLlamaCloud(api_key=settings.llamaextract_api_key)
    return _client


def get_client() -> AsyncLlamaCloud:
    """Return the process-wide client, or raise if the lifespan has not run."""

    if _client is None:
        raise RuntimeError(
            "LlamaCloud client is not initialised; is the application lifespan running?"
        )
    return _client


async def close_client() -> None:
    """Close the client and clear the holder."""

    global _client

    if _client is not None:
        await _client.close()
    _client = None
