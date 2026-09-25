# syntax=docker/dockerfile:1

FROM python:3.12-slim-bookworm AS builder

COPY --from=ghcr.io/astral-sh/uv:0.12.10 /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# Dependency layer: cached until the lock or project metadata changes.
# No cache mount for uv's own download cache: Railway's builder requires
# cache mount ids scoped to its own service id, which would hardcode a
# Railway-specific value into a Dockerfile that also has to work for plain
# `docker build`/docker-compose. The lockfile-based layer caching below is
# unaffected; this only makes a from-scratch build re-download packages
# instead of reusing a persistent uv cache.
RUN --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-install-project --no-dev

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
