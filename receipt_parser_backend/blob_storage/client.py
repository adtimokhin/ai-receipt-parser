"""Async S3-compatible client (aioboto3) for original document files.

There is no process-wide S3 client: :mod:`aioboto3` clients are
context-manager-scoped by design, so every operation opens a fresh client from
the module-level :class:`~aioboto3.Session` (whose construction does no I/O).
``ensure_bucket`` is idempotent: it is safe to run on every boot and in tests.
"""

from __future__ import annotations

from typing import Any

import aioboto3  # type: ignore[import-untyped]
from botocore.exceptions import ClientError  # type: ignore[import-untyped]

from receipt_parser_backend.config import get_settings

_BUCKET_ALREADY_OWNED_CODES = {"BucketAlreadyOwnedByYou", "BucketAlreadyExists"}

_session: aioboto3.Session | None = None


async def init_client() -> aioboto3.Session:
    """Build the session. Idempotent within a process. Does not perform I/O."""

    global _session

    _session = aioboto3.Session()
    return _session


def get_session() -> aioboto3.Session:
    """Return the process-wide session, or raise if the lifespan has not run."""

    if _session is None:
        raise RuntimeError(
            "Blob storage session is not initialised; is the application lifespan running?"
        )
    return _session


def _client_kwargs() -> dict[str, Any]:
    settings = get_settings()
    return {
        "endpoint_url": settings.blob_storage_endpoint_url or None,
        "aws_access_key_id": settings.blob_storage_access_key,
        "aws_secret_access_key": settings.blob_storage_secret_key,
        "region_name": settings.blob_storage_region,
    }


async def ensure_bucket() -> None:
    """Create the configured bucket if it does not exist yet."""

    settings = get_settings()
    async with get_session().client("s3", **_client_kwargs()) as s3:
        try:
            await s3.create_bucket(Bucket=settings.blob_storage_bucket)
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code", "")
            if code not in _BUCKET_ALREADY_OWNED_CODES:
                raise


async def upload_bytes(
    key: str, data: bytes, content_type: str = "application/octet-stream"
) -> None:
    """Upload ``data`` to ``key`` in the configured bucket."""

    settings = get_settings()
    async with get_session().client("s3", **_client_kwargs()) as s3:
        await s3.put_object(
            Bucket=settings.blob_storage_bucket, Key=key, Body=data, ContentType=content_type
        )


async def download_bytes(key: str) -> bytes:
    """Download and return the full contents of ``key``."""

    settings = get_settings()
    async with get_session().client("s3", **_client_kwargs()) as s3:
        response = await s3.get_object(Bucket=settings.blob_storage_bucket, Key=key)
        body: bytes = await response["Body"].read()
        return body


async def delete_object(key: str) -> None:
    """Delete ``key`` from the configured bucket."""

    settings = get_settings()
    async with get_session().client("s3", **_client_kwargs()) as s3:
        await s3.delete_object(Bucket=settings.blob_storage_bucket, Key=key)


async def close_client() -> None:
    """Reset the module-level session."""

    global _session

    _session = None
