# syntax=docker/dockerfile:1

FROM python:3.12-slim-bookworm AS builder

COPY --from=ghcr.io/astral-sh/uv:0.12.10 /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# Dependency layer: cached until the lock or project metadata changes.
# Plain COPY, not --mount=type=bind/cache: Railway's Dockerfile builder only
# supports a restricted subset of BuildKit mount syntax, and this Dockerfile
# also has to work for plain `docker build`/docker-compose. COPY here still
# keeps this layer cached separately from the full source (invalidated only
# when uv.lock/pyproject.toml change) - `COPY . /app` below overwrites these
# same two files with identical content, so there's no duplication cost.
COPY uv.lock pyproject.toml ./
RUN uv sync --locked --no-install-project --no-dev

COPY . /app
RUN uv sync --locked --no-dev


FROM python:3.12-slim-bookworm AS runtime

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

RUN groupadd --system app && useradd --system --gid app --home /app app

WORKDIR /app
COPY --from=builder --chown=app:app /app /app
USER app

EXPOSE 8000

# Exec form so SIGTERM reaches the process directly for graceful shutdown.
# uvicorn (not `fastapi run`) so the graceful-shutdown timeout is explicit.
CMD ["uvicorn", "receipt_parser_backend.main:app", \
     "--host", "0.0.0.0", "--port", "8000", \
     "--timeout-graceful-shutdown", "30"]
