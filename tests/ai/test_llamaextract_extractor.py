"""Real extraction port (spec 9.1), backed by LlamaCloud's Extract API."""

from __future__ import annotations

import json

import httpx
import pytest
from llama_cloud import AsyncLlamaCloud

from receipt_parser_backend.ai.extraction import ExtractionFailed
from receipt_parser_backend.ai.llamaextract_extractor import LlamaExtractExtractor
from receipt_parser_backend.countries.registry import US
from receipt_parser_backend.llamaextract import client as llamaextract_client_mod


def _install(
    monkeypatch: pytest.MonkeyPatch,
    *,
    job_status: str = "COMPLETED",
    extract_result: dict[str, object] | None = None,
    error_message: str | None = None,
    captured: list[httpx.Request] | None = None,
) -> None:
    upload_calls = {"count": 0}
    delete_calls: list[str] = []

    def _handler(request: httpx.Request) -> httpx.Response:
        if captured is not None:
            captured.append(request)
        path = request.url.path

        if request.method == "POST" and path.endswith("/files"):
            upload_calls["count"] += 1
            return httpx.Response(200, json={"id": "file-abc", "purpose": "extract"})

        if request.method == "POST" and path.endswith("/extract"):
            return httpx.Response(200, json={"id": "job-abc", "status": "PENDING"})

        if request.method == "GET" and "/extract/" in path:
            body: dict[str, object] = {"id": "job-abc", "status": job_status}
            if extract_result is not None:
                body["extract_result"] = extract_result
            if error_message is not None:
                body["error_message"] = error_message
            return httpx.Response(200, json=body)

        if request.method == "DELETE" and "/files/" in path:
            delete_calls.append(path.rsplit("/", 1)[-1])
            return httpx.Response(200, json={})

        return httpx.Response(404, json={"error": "unexpected request"})

    client = AsyncLlamaCloud(
        api_key="test-key",
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(_handler)),
        max_retries=0,
    )
    monkeypatch.setattr(llamaextract_client_mod, "_client", client)


_VALID_RESULT = {
    "merchant_name": "Fake Mart",
    "currency": "USD",
    "date": "01/15/2026",
    "time": "12:00",
    "items": [{"name": "Sample Item", "price": 9.99}],
    "discounts": 0.0,
    "tax": 0.8,
    "total": 10.79,
}


async def test_submit_returns_the_job_id(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch)
    job_id = await LlamaExtractExtractor().submit(b"file bytes", "application/pdf", US)
    assert job_id == "job-abc"


async def test_pending_job_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch, job_status="PENDING")
    extractor = LlamaExtractExtractor()
    job_id = await extractor.submit(b"file bytes", "application/pdf", US)
    assert await extractor.fetch_result(job_id) is None


async def test_completed_job_returns_parsed_raw_extraction(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch, job_status="COMPLETED", extract_result=_VALID_RESULT)
    extractor = LlamaExtractExtractor()
    job_id = await extractor.submit(b"file bytes", "application/pdf", US)
    result = await extractor.fetch_result(job_id)
    assert result is not None
    assert result.merchant_name == "Fake Mart"
    assert result.total == 10.79
    assert result.items[0].name == "Sample Item"


async def test_failed_job_raises_extraction_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch, job_status="FAILED", error_message="could not read the file")
    extractor = LlamaExtractExtractor()
    job_id = await extractor.submit(b"file bytes", "application/pdf", US)
    with pytest.raises(ExtractionFailed, match="could not read the file"):
        await extractor.fetch_result(job_id)


async def test_cancelled_job_raises_extraction_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch, job_status="CANCELLED")
    extractor = LlamaExtractExtractor()
    job_id = await extractor.submit(b"file bytes", "application/pdf", US)
    with pytest.raises(ExtractionFailed):
        await extractor.fetch_result(job_id)


async def test_uploaded_file_is_deleted_once_the_job_completes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[httpx.Request] = []
    _install(monkeypatch, job_status="COMPLETED", extract_result=_VALID_RESULT, captured=captured)
    extractor = LlamaExtractExtractor()
    job_id = await extractor.submit(b"file bytes", "application/pdf", US)
    await extractor.fetch_result(job_id)

    delete_requests = [r for r in captured if r.method == "DELETE"]
    assert len(delete_requests) == 1
    assert delete_requests[0].url.path.endswith("/files/file-abc")


async def test_uploaded_file_is_not_deleted_while_still_pending(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[httpx.Request] = []
    _install(monkeypatch, job_status="PENDING", captured=captured)
    extractor = LlamaExtractExtractor()
    job_id = await extractor.submit(b"file bytes", "application/pdf", US)
    await extractor.fetch_result(job_id)

    assert not any(r.method == "DELETE" for r in captured)


async def test_submit_sends_schema_prompt_and_disable_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[httpx.Request] = []
    _install(monkeypatch, captured=captured)
    await LlamaExtractExtractor().submit(b"file bytes", "application/pdf", US)

    extract_request = next(
        r for r in captured if r.method == "POST" and r.url.path.endswith("/extract")
    )
    body = json.loads(extract_request.content)
    configuration = body["configuration"]
    assert configuration["disable_cache"] is True
    assert configuration["system_prompt"] == US.extraction_prompt
    assert configuration["extraction_target"] == "per_doc"
    assert "data_schema" in configuration
