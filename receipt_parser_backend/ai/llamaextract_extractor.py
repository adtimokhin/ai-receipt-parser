"""Real extraction port (spec 9.1), backed by LlamaCloud's Extract API.

Submits the file's bytes directly (no temp files, no on-disk retention on
our side). ``disable_cache=True`` covers LlamaCloud's own reuse/storage of
the extract *result*; it does not cover the uploaded file itself, so this
also explicitly deletes that file once the job reaches a terminal state -
design rule 6 ("LlamaExtract must not retain files") needs both.
"""

from __future__ import annotations

import io

from llama_cloud.types import ExtractConfigurationParam

from receipt_parser_backend.ai.extraction import ALLOWED_MIME_TYPES, ExtractionFailed, RawExtraction
from receipt_parser_backend.countries import CountryProfile
from receipt_parser_backend.llamaextract.client import get_client

_TERMINAL_STATUSES = frozenset({"COMPLETED", "FAILED", "CANCELLED"})


class LlamaExtractExtractor:
    """The real :class:`~receipt_parser_backend.ai.extraction.ExtractorPort`."""

    def __init__(self) -> None:
        # job_id -> uploaded file_id, so the file can be deleted once the job
        # finishes. In-memory and best-effort: lost on a process restart, in
        # which case the file just sits until LlamaCloud's own expiry rather
        # than being deleted early - an accepted v1 limitation.
        self._uploaded_files: dict[str, str] = {}

    async def submit(self, file_bytes: bytes, mime_type: str, profile: CountryProfile) -> str:
        client = get_client()
        extension = ALLOWED_MIME_TYPES.get(mime_type, "bin")
        uploaded = await client.files.create(
            file=(f"receipt.{extension}", io.BytesIO(file_bytes), mime_type),
            purpose="extract",
        )
        configuration: ExtractConfigurationParam = {
            "data_schema": RawExtraction.model_json_schema(),
            "system_prompt": profile.extraction_prompt,
            "extraction_target": "per_doc",
            "disable_cache": True,
        }
        job = await client.extract.create(file_input=uploaded.id, configuration=configuration)
        self._uploaded_files[job.id] = uploaded.id
        return job.id

    async def fetch_result(self, job_id: str) -> RawExtraction | None:
        client = get_client()
        job = await client.extract.get(job_id)
        if job.status not in _TERMINAL_STATUSES:
            return None

        file_id = self._uploaded_files.pop(job_id, None)
        if file_id is not None:
            await client.files.delete(file_id)

        if job.status != "COMPLETED":
            raise ExtractionFailed(
                job.error_message or f"extraction job {job_id} {job.status.lower()}"
            )
        if not isinstance(job.extract_result, dict):
            raise ExtractionFailed(
                f"unexpected extract_result shape for job {job_id}: {job.extract_result!r}"
            )
        return RawExtraction.model_validate(job.extract_result)
