"""Proves the blob_storage overlay is wired into the running app (overlay-contract 7).

Mock mode (default): a local moto S3 server on loopback backs it, so upload,
download, delete, and the health check all run offline. Integration mode
(``tests_integration``): a real MinIO container backs it.
"""

from __future__ import annotations

import aioboto3  # type: ignore[import-untyped]

from receipt_parser_backend.blob_storage.client import (
    delete_object,
    download_bytes,
    get_session,
    upload_bytes,
)
from receipt_parser_backend.health import check_blob_storage
from receipt_parser_backend.lifespan import lifespan
from receipt_parser_backend.main import app


async def test_blob_storage_boots(blob_storage_client: object) -> None:
    async with lifespan(app):
        session = getattr(app.state, "blob_storage", None)
        assert session is not None, "blob_storage session missing from app.state"
        assert isinstance(session, aioboto3.Session)
        assert session is get_session()

        result = await check_blob_storage()
        assert result.healthy, result

        await upload_bytes("smoke/hello.txt", b"hello world", content_type="text/plain")
        assert await download_bytes("smoke/hello.txt") == b"hello world"
        await delete_object("smoke/hello.txt")
