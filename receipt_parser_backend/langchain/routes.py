"""LangChain sample route: ``POST /langchain/summarize``."""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

from receipt_parser_backend.langchain.chain import summarize_chain

router = APIRouter(prefix="/langchain", tags=["langchain"])


class SummarizeRequest(BaseModel):
    text: str = Field(description="Text to summarize.", min_length=1)


class SummarizeResponse(BaseModel):
    summary: str


@router.post(
    "/summarize",
    operation_id="langchain_summarize",
    summary="Summarize text with a LangChain prompt | model | parser chain.",
)
async def summarize_route(payload: SummarizeRequest) -> SummarizeResponse:
    result = await summarize_chain().ainvoke({"text": payload.text})
    return SummarizeResponse(summary=result)
