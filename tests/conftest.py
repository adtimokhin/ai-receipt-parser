"""Shared test fixtures.

Base-owned (overlay-contract 4.3). Overlays add fixtures through
``_fragments/<overlay-id>/conftest.py.jinja``, assembled in ``overlay_order``.
Overlay fixture names are namespaced ``<overlay-id>_<thing>``.
"""

from __future__ import annotations

import json
import os
from collections.abc import AsyncIterator, Iterator

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

# Collection-time placeholders for required-no-default secrets (D-030 class 2,
# D-037). ``setdefault`` never clobbers a real value; per-test fixtures still
# override via ``monkeypatch.setenv``. Needed because some overlay boots tests
# import the app at module scope, which builds ``Settings()`` before fixtures run.
os.environ.setdefault("APP_LLM_OPENAI_API_KEY", "test-collection-placeholder")
os.environ.setdefault("APP_TELEGRAM_BOT_TOKEN", "test-collection-placeholder")
os.environ.setdefault("APP_TELEGRAM_WEBHOOK_SECRET", "test-collection-placeholder")
os.environ.setdefault("APP_LLAMAEXTRACT_API_KEY", "test-collection-placeholder")


@pytest.fixture
def app() -> FastAPI:
    """A fresh application instance."""

    # Imported lazily: ``main`` builds ``app = create_app()`` -> ``Settings()`` at
    # import, so a module-scope import would raise ``ValidationError`` at pytest
    # collection when an overlay declares a required env var with no default.
    from receipt_parser_backend.main import create_app

    return create_app()


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    """Sync test client. Entering the context runs the app lifespan."""

    with TestClient(app) as test_client:
        yield test_client


# --- overlay fixtures (assembled in overlay_order) --------------------------


@pytest.fixture(autouse=True)
def mongodb_db(monkeypatch: pytest.MonkeyPatch) -> object:
    """Mock-mode client: a spec'd AsyncMock whose ``ping`` succeeds.

    Autouse so every test sees a stubbed, healthy datastore with no container.
    ``init_client`` is patched so the app lifespan installs this fake;
    ``isinstance(fake, AsyncMongoClient)`` still holds because the mock is spec'd.
    """
    from unittest.mock import AsyncMock

    from pymongo import AsyncMongoClient

    from receipt_parser_backend.db.mongodb import client as client_mod

    fake_admin = AsyncMock()
    fake_admin.command = AsyncMock(return_value={"ok": 1.0})

    fake_client = AsyncMock(spec=AsyncMongoClient)
    fake_client.admin = fake_admin
    fake_client.close = AsyncMock(return_value=None)

    def _fake_init() -> object:
        client_mod._client = fake_client
        return fake_client

    monkeypatch.setattr(client_mod, "init_client", _fake_init)
    return fake_client


@pytest.fixture
def fake_repository_db(monkeypatch: pytest.MonkeyPatch) -> object:
    """An in-memory Mongo stand-in for ``sessions/repository.py`` tests.

    Opt-in (not autouse): only session/pipeline/engine tests need real
    find/replace/insert/delete semantics; everything else is fine with the
    ping-only ``mongodb_db`` fake above.
    """
    from receipt_parser_backend.sessions import repository as repository_mod
    from tests.fakes.mongo import FakeMongoDatabase

    fake_db = FakeMongoDatabase()
    monkeypatch.setattr(repository_mod, "get_database", lambda: fake_db)
    return fake_db


@pytest.fixture(autouse=True)
def openai_client(monkeypatch: pytest.MonkeyPatch) -> Iterator[object]:
    """Mock mode: an httpx2 ``MockTransport`` wrapped in a real ``AsyncOpenAI`` (D-013).

    ``init_client`` is patched so the app lifespan installs a client whose
    transport returns canned Chat Completions JSON. No network, no real key.
    Autouse so the whole suite gets the offline client and a set API key.
    """
    import httpx2
    from openai import AsyncOpenAI, DefaultAsyncHttpxClient

    from receipt_parser_backend.config import get_settings
    from receipt_parser_backend.llm.openai import client as client_mod

    monkeypatch.setenv("APP_LLM_OPENAI_API_KEY", "test-key")
    get_settings.cache_clear()

    def _handler(_request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            200,
            json={
                "id": "chatcmpl-stub",
                "object": "chat.completion",
                "created": 0,
                "model": "gpt-4o-mini",
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": "This is a deterministic test summary.",
                        },
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            },
        )

    def _fake_init() -> AsyncOpenAI:
        client_mod._client = AsyncOpenAI(
            api_key="test-key",
            http_client=DefaultAsyncHttpxClient(transport=httpx2.MockTransport(_handler)),
            max_retries=0,
        )
        return client_mod._client

    monkeypatch.setattr(client_mod, "init_client", _fake_init)
    try:
        yield client_mod
    finally:
        get_settings.cache_clear()


FAKE_TELEGRAM_FILE_CONTENT = b"%PDF-fake-receipt-bytes"


@pytest.fixture(autouse=True)
def telegram_client(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[dict[str, object]]]:
    """Mock mode: a real ``httpx.AsyncClient`` with a ``MockTransport``.

    Records every ``sendMessage`` call's JSON body in the returned list, so
    tests can assert on outbound replies without any network access.
    ``getFile``/file-download requests get a canned, deterministic file
    (``FAKE_TELEGRAM_FILE_CONTENT``) so ``handle_document`` can be exercised
    end-to-end without a real Telegram file.
    """
    import httpx

    from receipt_parser_backend.telegram import client as client_mod

    sent: list[dict[str, object]] = []

    def _handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/sendMessage"):
            sent.append(json.loads(request.content))
            return httpx.Response(200, json={"ok": True, "result": {}})
        if request.url.path.endswith("/getFile"):
            return httpx.Response(
                200,
                json={"ok": True, "result": {"file_id": "fake", "file_path": "documents/fake.pdf"}},
            )
        if "/file/bot" in request.url.path:
            return httpx.Response(200, content=FAKE_TELEGRAM_FILE_CONTENT)
        return httpx.Response(200, json={"ok": True, "result": {}})

    def _fake_init() -> httpx.AsyncClient:
        client_mod._client = httpx.AsyncClient(
            base_url="https://api.telegram.org/bottest-token",
            transport=httpx.MockTransport(_handler),
        )
        return client_mod._client

    monkeypatch.setattr(client_mod, "init_client", _fake_init)
    _fake_init()  # so tests that call the pipeline directly (no app lifespan) still get a client
    try:
        yield sent
    finally:
        client_mod._client = None


@pytest.fixture(autouse=True)
async def blob_storage_client(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[str]:
    """Mock-mode client: a local moto S3 server on loopback (no Docker, no real AWS).

    Autouse so every test sees a working, healthy blob store. moto's decorator-based
    ``mock_aws`` does not intercept aioboto3/aiobotocore's aiohttp transport (a known
    moto limitation), so this starts a real ``ThreadedMotoServer`` on an ephemeral
    loopback port instead and points settings at it, exactly like a real S3-compatible
    endpoint. No I/O leaves the machine.
    """
    from moto.server import ThreadedMotoServer

    from receipt_parser_backend.blob_storage import client as client_mod
    from receipt_parser_backend.config import get_settings

    server = ThreadedMotoServer(ip_address="127.0.0.1", port=0, verbose=False)
    server.start()
    host, port = server.get_host_and_port()
    endpoint_url = f"http://{host}:{port}"

    monkeypatch.setenv("APP_BLOB_STORAGE_ENDPOINT_URL", endpoint_url)
    get_settings.cache_clear()
    # So tests that call the pipeline directly (no app lifespan) still get a
    # session and an existing bucket - matches the telegram_client fixture's
    # reasoning, and the app lifespan's own ensure_bucket() call.
    await client_mod.init_client()
    await client_mod.ensure_bucket()
    try:
        yield endpoint_url
    finally:
        get_settings.cache_clear()
        await client_mod.close_client()
        server.stop()
