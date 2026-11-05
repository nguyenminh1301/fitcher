FROM ghcr.io/astral-sh/uv:0.13.6 AS uv
FROM python:3.13.18-slim-bookworm AS build

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:$PATH"

COPY --from=uv /uv /usr/local/bin/uv
WORKDIR /app
COPY apps/api/pyproject.toml apps/api/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project --no-managed-python

FROM python:3.13.18-slim-bookworm AS runtime
RUN apt-get update && apt-get upgrade -y --no-install-recommends \
    && rm -rf /var/lib/apt/lists/* \
    && python -m pip uninstall -y pip \
    && rm -rf /usr/local/lib/python3.13/ensurepip
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"
WORKDIR /app
COPY --from=build /app/.venv ./.venv
COPY apps/api/app ./app
COPY apps/api/prompts ./prompts
COPY jobs ./jobs
COPY dbt ./dbt
COPY packs ./packs
# jobs.screen_eval reads the engine-level benign and attack screening sets.
COPY apps/api/tests/screening ./tests/screening
# jobs.apply_log_schema applies the same DDL that initdb runs on a fresh volume.
COPY infra/clickhouse/initdb ./infra/clickhouse/initdb
# jobs.set_lab_passwords reads the lab users of the realm Keycloak imports.
COPY infra/keycloak/realm-finch.json ./infra/keycloak/realm-finch.json
# Compiled packs live in a named volume mounted here; Docker copies this
# directory's owner into a new volume, so the app user can write to it.
RUN useradd --create-home --uid 10001 app     && mkdir -p /app/build/packs /app/build/guard_model /app/build/documents     && chown app /app/build/packs /app/build/documents
USER app

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
