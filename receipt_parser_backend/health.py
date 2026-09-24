"""Liveness and readiness.

* ``GET /health/live``  - process is up. No dependency checks. Always cheap.
* ``GET /health/ready`` - every registered readiness check passed. Returns 200
  when ready, 503 with a per-check body otherwise.

Base-owned shared file (overlay-contract 4.3). Overlays add one async check
function through ``_fragments/<overlay-id>/health.py.jinja`` and append it to
``READINESS_CHECKS``. The list is walked in ``overlay_order``.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from fastapi import APIRouter, Response, status

router = APIRouter(tags=["health"])


@dataclass(frozen=True)
class HealthResult:
    """Outcome of a single readiness check."""

    name: str
    healthy: bool
    detail: str = ""


ReadinessCheck = Callable[[], Awaitable[HealthResult]]

# Overlays append their check callables here, in overlay_order.
READINESS_CHECKS: list[ReadinessCheck] = []

# --- overlay readiness checks (assembled in overlay_order) -------------------


async def check_db_mongodb() -> HealthResult:
    """Readiness probe: the ``ping`` admin command (no auth, any database)."""
    from receipt_parser_backend.db.mongodb.client import get_client

    try:
        await get_client().admin.command("ping")
    except Exception as exc:  # readiness must never raise
        return HealthResult(name="db_mongodb", healthy=False, detail=repr(exc))
    return HealthResult(name="db_mongodb", healthy=True)


READINESS_CHECKS.append(check_db_mongodb)


async def check_llm_openai() -> HealthResult:
    """Readiness probe: the client is built and an API key is configured.

    No network round-trip - an LLM call on every readiness poll would burn
    tokens and add latency. This proves the wiring, not the upstream's health.
    """
    from receipt_parser_backend.config import get_settings
    from receipt_parser_backend.llm.openai.client import get_client

    try:
        get_client()
    except RuntimeError as exc:  # lifespan has not run
        return HealthResult(name="llm_openai", healthy=False, detail=repr(exc))
    configured = bool(get_settings().llm_openai_api_key)
    return HealthResult(
        name="llm_openai",
        healthy=configured,
        detail="api key configured" if configured else "APP_LLM_OPENAI_API_KEY is empty",
    )


READINESS_CHECKS.append(check_llm_openai)


async def check_blob_storage() -> HealthResult:
    """Readiness probe: ``head_bucket`` (also validates connectivity and auth)."""
    from receipt_parser_backend.blob_storage.client import get_session
    from receipt_parser_backend.config import get_settings

    try:
        settings = get_settings()
        async with get_session().client(
            "s3",
            endpoint_url=settings.blob_storage_endpoint_url or None,
            aws_access_key_id=settings.blob_storage_access_key,
            aws_secret_access_key=settings.blob_storage_secret_key,
            region_name=settings.blob_storage_region,
        ) as s3:
            await s3.head_bucket(Bucket=settings.blob_storage_bucket)
    except Exception as exc:  # readiness must never raise
        return HealthResult(name="blob_storage", healthy=False, detail=repr(exc))
    return HealthResult(name="blob_storage", healthy=True)


READINESS_CHECKS.append(check_blob_storage)


async def _run_check(check: ReadinessCheck) -> HealthResult:
    try:
        return await check()
    except Exception as exc:  # a check must never break readiness itself
        name = getattr(check, "__name__", "check")
        return HealthResult(name=name, healthy=False, detail=repr(exc))


async def readiness() -> tuple[bool, dict[str, dict[str, object]]]:
    """Run every readiness check concurrently and aggregate the results."""

    results = await asyncio.gather(*(_run_check(check) for check in READINESS_CHECKS))
    body = {r.name: {"healthy": r.healthy, "detail": r.detail} for r in results}
    return all(r.healthy for r in results), body


@router.get("/health/live")
async def live() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/health/ready")
async def ready(response: Response) -> dict[str, object]:
    ok, checks = await readiness()
    response.status_code = status.HTTP_200_OK if ok else status.HTTP_503_SERVICE_UNAVAILABLE
    return {"status": "ready" if ok else "not_ready", "checks": checks}
