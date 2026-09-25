"""Application settings.

Base-owned pydantic-settings loader (D-021). Every environment variable is read
with the ``APP_`` prefix, so ``environment`` comes from ``APP_ENVIRONMENT``.

Overlays never ship their own loader. They contribute field declarations through
``_fragments/<overlay-id>/settings.py.jinja``, which are assembled into the
``Settings`` class body below in ``overlay_order``.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration, loaded once and cached by :func:`get_settings`."""

    model_config = SettingsConfigDict(
        env_prefix="APP_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- base fields -----------------------------------------------------------
    environment: str = "local"
    log_level: str = "INFO"
    json_logs: bool = True
    service_name: str = "receipt-parser-backend"

    # --- overlay fields (assembled in overlay_order) -------------------------
    db_mongodb_uri: str = "mongodb://mongodb:27017"
    db_mongodb_database: str = "receipt-parser-backend"
    db_mongodb_server_selection_timeout_ms: int = 3000
    llm_openai_api_key: str
    llm_openai_model: str = "gpt-4o-mini"
    llm_openai_timeout_s: int = 30
    llm_openai_base_url: str | None = None
    blob_storage_endpoint_url: str | None = "http://minio:9000"
    blob_storage_access_key: str = "minioadmin"
    blob_storage_secret_key: str = "minioadmin"
    blob_storage_bucket: str = "receipt-parser-backend"
    blob_storage_region: str = "us-east-1"

    # --- telegram --------------------------------------------------------------
    telegram_bot_token: str
    telegram_webhook_secret: str
    # Comma-separated Telegram user IDs, e.g. "123,456". Kept as a plain string
    # field (see telegram_whitelist_ids below) so pydantic-settings never tries
    # to JSON-decode it as a complex env value.
    telegram_whitelist: str = ""

    # --- llamaextract ------------------------------------------------------------
    # The current llama-cloud SDK takes schema/prompt inline per extract.create()
    # call (spec 9.1) - no persistent extraction agent to configure.
    llamaextract_api_key: str

    @property
    def telegram_whitelist_ids(self) -> list[int]:
        """Parsed whitelist (spec 4.1)."""

        return [int(item) for item in self.telegram_whitelist.split(",") if item.strip()]


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide :class:`Settings`, building it on first use."""

    return Settings()
