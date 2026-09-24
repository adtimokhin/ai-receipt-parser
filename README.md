# receipt-parser-backend

A single-user Telegram bot that turns receipt files into structured records.
See `../receipt-parser-state-machine.md` for the full spec and
`../coding-agent-prompt.md` for the build process this repo follows.

## Requirements

- Python 3.12+
- [uv](https://docs.astral.sh/uv/)
- Docker (optional, for the container and compose stack)

## Setup

```bash
uv lock          # first time, and after any dependency change
uv sync          # create .venv and install everything
cp .env.example .env
```

`uv.lock` is committed. CI runs `uv sync --locked`.

## Configuration

All settings are environment variables with an `APP_` prefix (see
`.env.example` for the full list and local-dev defaults):

- `APP_DB_MONGODB_*` - MongoDB connection (sessions, user settings, receipts).
- `APP_LLM_OPENAI_*` - OpenAI client, used by the reply interpreter (spec 9.2).
- `APP_BLOB_STORAGE_*` - S3-compatible client for original/preprocessed
  receipt files. Local dev points at the `minio` compose service; production
  points at [Cloudflare R2](https://developers.cloudflare.com/r2/) (S3-compatible).
- `APP_TELEGRAM_BOT_TOKEN` / `APP_TELEGRAM_WEBHOOK_SECRET` - bot credentials.
  The webhook secret is compared against Telegram's
  `X-Telegram-Bot-Api-Secret-Token` header on every incoming update.
- `APP_TELEGRAM_WHITELIST` - comma-separated Telegram user IDs allowed to use
  the bot. Updates from anyone else are dropped (spec 4.1).
- `APP_LLAMAEXTRACT_*` - LlamaExtract credentials used for receipt extraction
  (spec 9.1). Jobs are submitted with `do_not_cache=True` so files are never
  retained on LlamaCloud (design rule 6).

## Country profiles

Country-specific behavior (date/decimal formats, tax model, extraction and
interpreter prompts) lives in
`receipt_parser_backend/countries/registry.py`, one `CountryProfile` per
supported country. v1 ships `US` and `FR`. Adding a country means adding a
profile there — pipeline code never branches on country code directly (spec
Section 5, design rule 5).

## Telegram bot setup

Webhook registration and the ingress endpoint land in a later milestone; this
section will document `setWebhook` and secret-token setup once they exist.

## Run

```bash
uv run fastapi dev receipt_parser_backend/main.py     # local, with reload
uv run uvicorn receipt_parser_backend.main:app        # production-style
```

- `GET /` - service identity
- `GET /health/live` - liveness, no dependency checks
- `GET /health/ready` - readiness, aggregates all registered checks

Every request gets an `X-Request-ID` (generated when absent) that is echoed on
the response and attached to every log line.

## Test

```bash
uv run pytest
```

## Lint, format, and type-check

```bash
uv run ruff format .        # apply the formatter
uv run ruff format --check . # verify only (what CI runs)
uv run ruff check .
uv run mypy
```

## Git hooks

A pre-commit hook runs `ruff format` and `ruff check` on staged Python and
**blocks the commit** if anything is not formatted or lints dirty (same ruff as
CI, from `uv.lock`). It is installed for you when you generate into an existing
git repo; otherwise activate it once:

```bash
uv run pre-commit install
uv run pre-commit run --all-files   # check everything now
```

## Claude Code hooks

`.claude/hooks/` holds vendored [Claude Code hooks](https://github.com/karanb192/claude-code-hooks)
(MIT) wired by `.claude/settings.json`: dev-safety guardrails and auto-format.
They need `node >=18` on `PATH` and fail open if it is missing. See
`.claude/hooks/VENDORED.md`. Change which hooks are active with `copier update`
(the `hook_*` answers), not by hand-editing `settings.json`.

## Container

```bash
docker compose up --build
```

The compose stack builds the `runtime` image target and runs the app with a
`/health/live` healthcheck.

## Updating from the template

This project keeps `.copier-answers.yml` so it can pull template
changes:

```bash
copier update
uv lock && uv sync
```

Never edit `.copier-answers.yml` by hand.

## License

Proprietary and confidential.
