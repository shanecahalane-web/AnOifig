# Keep this version aligned with .python-version and CI.
FROM ghcr.io/astral-sh/uv:0.12.23 AS uv
FROM python:3.13-slim-bookworm AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_PYTHON_DOWNLOADS=never \
    UV_NO_CACHE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    PATH="/app/.venv/bin:$PATH"
COPY --from=uv /uv /uvx /usr/local/bin/
WORKDIR /app

FROM base AS dependencies
COPY pyproject.toml uv.lock README.md ./
RUN --mount=type=secret,id=build_ca,target=/etc/ssl/certs/ca-certificates.crt \
    UV_SYSTEM_CERTS=1 uv sync --frozen --no-dev --no-install-project
COPY src ./src
RUN --mount=type=secret,id=build_ca,target=/etc/ssl/certs/ca-certificates.crt \
    UV_SYSTEM_CERTS=1 uv sync --frozen --no-dev

FROM dependencies AS development
RUN --mount=type=secret,id=build_ca,target=/etc/ssl/certs/ca-certificates.crt \
    UV_SYSTEM_CERTS=1 uv sync --frozen
COPY alembic.ini ./
COPY migrations ./migrations
COPY tests ./tests
COPY scripts ./scripts
RUN groupadd --gid 10001 anoifig && useradd --uid 10001 --gid 10001 --no-create-home anoifig \
    && chown -R anoifig:anoifig /app
USER anoifig
CMD ["uv", "run", "--no-sync", "uvicorn", "anoifig.api.main:app", "--host", "0.0.0.0", "--port", "8000"]

FROM base AS runtime
COPY --from=dependencies /app/.venv /app/.venv
COPY pyproject.toml uv.lock alembic.ini ./
COPY src ./src
COPY migrations ./migrations
COPY scripts ./scripts
RUN groupadd --gid 10001 anoifig && useradd --uid 10001 --gid 10001 --no-create-home anoifig \
    && chown -R anoifig:anoifig /app
USER anoifig
EXPOSE 8000
CMD ["uv", "run", "--no-sync", "uvicorn", "anoifig.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
