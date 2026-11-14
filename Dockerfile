# syntax=docker/dockerfile:1.7
# The release image (DECISIONS §3): web, api, an embedded ClickHouse and Qdrant supervised by s6-overlay
# in one container, one data volume (/data) and one published port (3000). compose.yaml keeps the
# development layout of separate services. Versions match compose.yaml; base images are pinned by digest.

ARG PYTHON_IMAGE=python:3.13.18-slim-trixie@sha256:e48f59cdba69a3cbd9ed2cf0f348d90d45a8d350d98134cf1070bc106ee9ed90
ARG NODE_BUILD_IMAGE=node:24.21.0-bookworm-slim@sha256:d6aa754f16b3197301076f047b5def2f02ea1dbbc2ca920407d46d7ec7f87b20
ARG NODE_IMAGE=node:24.21.0-trixie-slim@sha256:173f125896c3b47ddf056734c7ea789d04595a6a08769a8f78e0df642781fb66
ARG CLICKHOUSE_IMAGE=clickhouse/clickhouse-server:26.8.36.3@sha256:d426d2f612e1e189c90f9a3f8dcd85a03c6851273833817a296bb327e63aa7a7
ARG QDRANT_IMAGE=qdrant/qdrant:v1.20.0@sha256:9bfc89f9914fc14876a88c05270685921a55b8877b254a98bcc1cc2f0a424cd2
ARG UV_IMAGE=ghcr.io/astral-sh/uv:0.13.6@sha256:af22a52f5eafef3d78e551599d405c02df61919d18028f0cea8eda93bc9986d0

FROM ${UV_IMAGE} AS uv
FROM ${CLICKHOUSE_IMAGE} AS clickhouse
FROM ${QDRANT_IMAGE} AS qdrant
FROM ${NODE_IMAGE} AS node

FROM ${NODE_BUILD_IMAGE} AS web-build
WORKDIR /app
ENV NEXT_TELEMETRY_DISABLED=1
COPY apps/web/package.json apps/web/package-lock.json ./
RUN npm ci
COPY apps/web ./
RUN npm run build

FROM ${PYTHON_IMAGE} AS api-build
ENV PYTHONDONTWRITEBYTECODE=1 UV_LINK_MODE=copy
COPY --from=uv /uv /usr/local/bin/uv
WORKDIR /app
COPY apps/api/pyproject.toml apps/api/uv.lock ./
# Runtime dependencies only: the dev and jobs groups (pytest, dbt) are development tools.
RUN uv sync --frozen --no-default-groups --no-install-project --no-managed-python

# s6-overlay, verified against the checksums published with release v3.2.3.2.
FROM ${PYTHON_IMAGE} AS s6
ARG TARGETARCH
ARG S6_OVERLAY_VERSION=v3.2.3.2
ADD --checksum=sha256:5379750ed30a84bbd2e2dd74847ba6b5bd29cd0b2e3ea2ec58049b57eb2eda12 \
    https://github.com/just-containers/s6-overlay/releases/download/${S6_OVERLAY_VERSION}/s6-overlay-noarch.tar.xz /tmp/
ADD --checksum=sha256:e6befcc96a437a3831386ecfc51808c5d3e939dc5fe3c02ae9284599e8aa2408 \
    https://github.com/just-containers/s6-overlay/releases/download/${S6_OVERLAY_VERSION}/s6-overlay-x86_64.tar.xz /tmp/
ADD --checksum=sha256:b17f17a82e7a515c682a91edaf2ffdabb73f891981b6c1fd712115693a2f8b4c \
    https://github.com/just-containers/s6-overlay/releases/download/${S6_OVERLAY_VERSION}/s6-overlay-aarch64.tar.xz /tmp/
RUN apt-get update && apt-get install -y --no-install-recommends xz-utils \
    && case "${TARGETARCH}" in amd64) arch=x86_64 ;; arm64) arch=aarch64 ;; *) echo "unsupported ${TARGETARCH}" >&2; exit 1 ;; esac \
    && mkdir /s6 \
    && tar -C /s6 -Jxpf /tmp/s6-overlay-noarch.tar.xz \
    && tar -C /s6 -Jxpf "/tmp/s6-overlay-${arch}.tar.xz"

FROM ${PYTHON_IMAGE} AS runtime
# libunwind8 is the one library the Qdrant binary needs beyond the base image.
RUN apt-get update && apt-get upgrade -y --no-install-recommends \
    && apt-get install -y --no-install-recommends libunwind8 \
    && rm -rf /var/lib/apt/lists/* \
    && python -m pip uninstall -y pip \
    && rm -rf /usr/local/lib/python3.13/ensurepip
COPY --from=s6 /s6/ /
COPY --from=clickhouse /usr/bin/clickhouse /usr/bin/clickhouse
COPY --from=clickhouse /etc/clickhouse-server/config.xml /etc/clickhouse-server/users.xml /etc/clickhouse-server/
COPY --from=qdrant /qdrant/qdrant /opt/qdrant/qdrant
COPY --from=qdrant /qdrant/config /opt/qdrant/config
COPY --from=node /usr/local/bin/node /usr/local/bin/node
RUN ln -s /usr/bin/clickhouse /usr/bin/clickhouse-server && ln -s /usr/bin/clickhouse /usr/bin/clickhouse-client

WORKDIR /app
COPY --from=api-build /app/.venv ./.venv
COPY apps/api/app ./app
COPY apps/api/prompts ./prompts
COPY jobs ./jobs
COPY infra/clickhouse/changes ./infra/clickhouse/changes
COPY infra/clickhouse/users.d ./infra/clickhouse/users.d
COPY infra/image/clickhouse ./infra/image/clickhouse
COPY --from=web-build /app/.next/standalone /opt/web/
COPY --from=web-build /app/.next/static /opt/web/.next/static
COPY infra/image/s6-rc.d /etc/s6-overlay/s6-rc.d
COPY infra/image/user-bundles.d /etc/s6-overlay/user-bundles.d
COPY infra/image/scripts /etc/s6-overlay/scripts
COPY infra/image/healthcheck.sh /usr/local/bin/fitcher-healthcheck
COPY infra/image/fitcher /usr/local/bin/fitcher

# Every service runs as the application user; s6-overlay needs /run writable by it. Docker copies the owner
# of /data into a new named volume, so the user owns a fresh volume.
RUN useradd --create-home --uid 10001 app \
    && mkdir -p /data /run/fitcher \
    && chown app:app /data /run /run/fitcher \
    && chmod 0755 /usr/local/bin/fitcher /usr/local/bin/fitcher-healthcheck /etc/s6-overlay/scripts/* \
        /etc/s6-overlay/s6-rc.d/*/run /etc/s6-overlay/s6-rc.d/*/finish

# A failing init-data or migrate stops the container; at shutdown services get 8 s, within the 10 s of docker stop.
ENV PATH="/app/.venv/bin:/command:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    FITCHER_DATA_DIR=/data \
    FITCHER_RUN_DIR=/run/fitcher \
    CLICKHOUSE_STOCK_CONFIG=/etc/clickhouse-server \
    PACKS_DIR=/data/packs \
    COMPILED_PACK_DIR=/data/compiled \
    DOCUMENTS_DIR=/data/documents \
    GUARD_MODEL_DIR=/data/models/guard \
    QDRANT_URL=http://127.0.0.1:6333 \
    HF_HUB_DISABLE_TELEMETRY=1 \
    NEXT_TELEMETRY_DISABLED=1 \
    S6_BEHAVIOUR_IF_STAGE2_FAILS=2 \
    S6_CMD_WAIT_FOR_SERVICES_MAXTIME=0 \
    S6_SERVICES_GRACETIME=8000 \
    S6_KILL_GRACETIME=1000 \
    S6_VERBOSITY=1

USER app
VOLUME /data
EXPOSE 3000
HEALTHCHECK --interval=10s --timeout=5s --start-period=60s --retries=6 CMD ["/usr/local/bin/fitcher-healthcheck"]
ENTRYPOINT ["/init"]
