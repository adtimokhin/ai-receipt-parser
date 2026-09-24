"""Root endpoint: a minimal service identity response."""

from fastapi import APIRouter

from receipt_parser_backend.config import get_settings

router = APIRouter(tags=["root"])


@router.get("/")
async def root() -> dict[str, str]:
    settings = get_settings()
    return {
        "service": settings.service_name,
        "environment": settings.environment,
    }
