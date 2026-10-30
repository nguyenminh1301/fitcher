# Phase 0: Repository foundation and infrastructure

## Goal

Turn the monorepo scaffold into a running lab environment: the six long-running services from DECISIONS §3 start with one command, each reports healthy, and the `fast` alias answers through LiteLLM.

## Scope

- Compose definitions for `clickhouse`, `opensearch`, `litellm`, `keycloak`, `api`, `web`.
- Minimal configuration under `infra/`: ClickHouse users and databases, LiteLLM aliases, a placeholder Keycloak realm.
- `make up` / `make down` and equivalent documented `docker compose` commands.
- CI and security workflows updated for the new services.

## Out of scope

- Any data load, dbt project or pack content (Phases 1-2).
- Realm roles and users beyond a placeholder realm (Phase 6).
- Application logic in `api` or `web`; both stay skeletons serving health/placeholder pages.

## Prerequisites

- Monorepo scaffold: `apps/api` (FastAPI `GET /health`), `apps/web` (placeholder page), `packs/`, `dbt/`, `jobs/`, `infra/`, `docs/`.
- An `OPENAI_API_KEY` in the developer's `.env` for the single explicit alias smoke call.

## Deliverables

```text
compose.yaml                      # or infra/compose.yaml, see open question 1
Makefile                          # up, down, ps, logs, smoke
.env.example                      # every variable below, no real secrets
infra/
  clickhouse/
    config.d/listen.xml           # loopback-only exposure is handled by Compose ports
    users.d/users.xml             # admin user from env; default user disabled
    initdb/001-databases.sql      # CREATE DATABASE IF NOT EXISTS raw, marts
  litellm/config.yaml             # model_list with fast, sql-gen, sql-gen-hard, embed
  keycloak/realm-finch.json       # realm "finch", one public web client, no users yet
  opensearch/                     # README only unless JVM or plugin settings are needed
```

## Tasks

1. **ClickHouse service.** Pin an exact `clickhouse/clickhouse-server` tag. Mount `users.d` and `initdb`. Disable the passwordless `default` user; create an admin user from `CLICKHOUSE_ADMIN_PASSWORD`. Healthcheck: HTTP `GET /ping` on 8123. Named volume `clickhouse-data`.
2. **OpenSearch service.** Pin an exact `opensearchproject/opensearch` tag that supports hybrid search pipelines and `knn_vector`. Single-node discovery, security plugin disabled for the lab, bounded heap (`OPENSEARCH_JAVA_OPTS`). Healthcheck: `_cluster/health?wait_for_status=yellow`. Document `vm.max_map_count` for Linux hosts and WSL2.
3. **LiteLLM service.** Pin an exact `ghcr.io/berriai/litellm` tag. `infra/litellm/config.yaml` maps the four aliases to OpenAI models through environment variables (`LITELLM_MODEL_FAST`, `LITELLM_MODEL_SQL_GEN`, `LITELLM_MODEL_SQL_GEN_HARD`, `LITELLM_MODEL_EMBED`), so model changes need no code change. `LITELLM_MASTER_KEY` protects the proxy. Healthcheck: `/health/liveliness`, which must not call OpenAI.
4. **Keycloak service.** Pin an exact `quay.io/keycloak/keycloak` tag, run `start-dev --import-realm` with `KC_HEALTH_ENABLED=true`. Healthcheck on the management `health/ready` endpoint. The realm contains client `finch-web` only.
5. **api and web services.** Keep the skeleton images. `api` depends on healthy `clickhouse`, `opensearch` and `litellm`; `web` depends on healthy `api` and `keycloak`. The `api` image also carries `jobs/` (open question 2).
6. **Make targets and docs.** `make up` = `docker compose up --build --wait`; `make down` = `docker compose down` (never `-v`). `make smoke` runs one explicit, billable `fast` call. README documents the plain `docker compose` equivalents for PowerShell users.
7. **CI and security.** Repository and app jobs unchanged; `docker compose config --quiet` added to CI. The image audit covers every runtime image: `api` and `web` are rebuilt and scanned as today, and the four third-party images are scanned by their pinned tags with the same fixable High/Critical gate and complete report artifacts. A finding only an upstream release can fix follows the SECURITY.md exception record (advisory, image, evidence, owner, expiry); the gate is never weakened silently.

## Contracts

New `.env.example` keys: `CLICKHOUSE_ADMIN_USER`, `CLICKHOUSE_ADMIN_PASSWORD`, `LITELLM_MASTER_KEY`, `LITELLM_MODEL_FAST`, `LITELLM_MODEL_SQL_GEN`, `LITELLM_MODEL_SQL_GEN_HARD`, `LITELLM_MODEL_EMBED`, `OPENAI_API_KEY` (LiteLLM container only), `KEYCLOAK_ADMIN`, `KEYCLOAK_ADMIN_PASSWORD`, `OPENSEARCH_JAVA_OPTS`.
`OPENAI_API_KEY` is passed only to `litellm`; `api` receives `LITELLM_BASE_URL` and `LITELLM_MASTER_KEY`.

## Verification

```bash
docker compose config --quiet
make up                     # or: docker compose up --build --wait
docker compose ps           # six services, all healthy
curl -fsS http://127.0.0.1:8000/health
make smoke                  # explicit billable call to alias fast through LiteLLM
make down
```

Plus the base checks: `python scripts/check_repository.py`, `python scripts/check_git.py --range origin/develop..HEAD`, actionlint for workflow changes.

## Definition of done

| DoD item | Proof |
|---|---|
| `make up` starts all 6 services, all healthy | `docker compose ps` output in the PR |
| `fast` alias callable through LiteLLM | `make smoke` exit 0 and a non-empty reply (text not logged) |
| `api /health` returns OK | `curl` output |

## Risks and open questions

1. **Compose file location.** DECISIONS §13 lists compose under `infra/`. Default: keep `compose.yaml` at the root so plain `docker compose` works, and keep service configuration under `infra/`. Alternative: `infra/compose.yaml` with every command using `-f`.
2. **Jobs and the api image.** DECISIONS §3 says jobs share the `api` image while §13 puts them in root `jobs/`. Default: the `api` Dockerfile builds from the repository root and copies `apps/api` and `jobs/`; job dependencies live in a `jobs` dependency group of `apps/api/pyproject.toml`.
3. **`make` on Windows.** `make` is not part of a stock PowerShell setup. Default: keep the Makefile thin and document every target as a `docker compose` command; do not add a second task runner.
4. **Memory footprint.** Six services plus OpenSearch heap may exceed small laptops. Default: document the minimum (about 8 GB free for Docker) and cap the OpenSearch heap at 1 GB.
5. **Image versions.** Exact tags are chosen and verified at phase start; DECISIONS does not pin them.
6. **Upstream image findings.** Third-party images may carry fixable advisories that only upstream can patch. Default: choose the newest patched tag; otherwise record a SECURITY.md exception.

## Branch and PR split

- `feat/infra/compose-lab-services`: tasks 1-6 (expected `size/M`).
- Workflow changes from task 7 ride in the same PR unless it exceeds `size/M`; then a follow-up `chore/ci/check-lab-service-compose` branch carries them.
