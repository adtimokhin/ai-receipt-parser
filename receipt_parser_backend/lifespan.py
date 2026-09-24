"""Application lifespan.

Base-owned shared file (overlay-contract 4.5). The base keeps two ordered
registries of async hooks. Each overlay contributes one startup hook and one
shutdown hook through ``_fragments/<overlay-id>/lifespan.py.jinja`` and appends
them to the registries.

Startup runs the hooks in ``overlay_order``. Shutdown runs them in reverse.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI

LifecycleHook = Callable[[FastAPI], Awaitable[None]]

# Overlays append their hooks here, in overlay_order.
STARTUP_HOOKS: list[LifecycleHook] = []
SHUTDOWN_HOOKS: list[LifecycleHook] = []

# --- overlay lifecycle hooks (assembled in overlay_order) -------------------


async def _db_mongodb_startup(app: FastAPI) -> None:
    from receipt_parser_backend.db.mongodb.client import init_client

    app.state.db_mongodb = init_client()


async def _db_mongodb_shutdown(app: FastAPI) -> None:
    from receipt_parser_backend.db.mongodb.client import close_client

    await close_client()


STARTUP_HOOKS.append(_db_mongodb_startup)
SHUTDOWN_HOOKS.append(_db_mongodb_shutdown)


async def _llm_openai_startup(app: FastAPI) -> None:
    from receipt_parser_backend.llm.openai.client import init_client

    app.state.llm_openai = init_client()


async def _llm_openai_shutdown(app: FastAPI) -> None:
    from receipt_parser_backend.llm.openai.client import close_client

    await close_client()


STARTUP_HOOKS.append(_llm_openai_startup)
SHUTDOWN_HOOKS.append(_llm_openai_shutdown)


async def _blob_storage_startup(app: FastAPI) -> None:
    import structlog

    from receipt_parser_backend.blob_storage.client import ensure_bucket, init_client

    app.state.blob_storage = await init_client()
    try:
        await ensure_bucket()
    except Exception as exc:  # bootstrap is best-effort; readiness reports the truth
        structlog.get_logger(__name__).warning("blob_storage.ensure_bucket_failed", error=repr(exc))


async def _blob_storage_shutdown(app: FastAPI) -> None:
    from receipt_parser_backend.blob_storage.client import close_client

    await close_client()


STARTUP_HOOKS.append(_blob_storage_startup)
SHUTDOWN_HOOKS.append(_blob_storage_shutdown)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Run overlay startup hooks, serve, then run shutdown hooks in reverse."""

    for hook in STARTUP_HOOKS:
        await hook(app)
    try:
        yield
    finally:
        for hook in reversed(SHUTDOWN_HOOKS):
            await hook(app)
