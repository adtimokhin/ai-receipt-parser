"""Application entrypoint.

``create_app()`` is a factory so tests can build isolated instances. The module
level ``app`` is what ``fastapi run receipt_parser_backend/main.py`` serves.
"""

from __future__ import annotations

from fastapi import FastAPI

from receipt_parser_backend import __version__
from receipt_parser_backend.api import api_router
from receipt_parser_backend.config import get_settings
from receipt_parser_backend.health import router as health_router
from receipt_parser_backend.lifespan import lifespan
from receipt_parser_backend.logging_config import configure_logging
from receipt_parser_backend.middleware import CorrelationIdMiddleware


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(json_logs=settings.json_logs, level=settings.log_level)

    app = FastAPI(
        title="receipt-parser-backend",
        version=__version__,
        lifespan=lifespan,
    )

    # Outermost middleware: every downstream log line and the access log carry
    # the correlation id.
    app.add_middleware(CorrelationIdMiddleware)

    app.include_router(health_router)
    app.include_router(api_router)

    return app


app = create_app()
