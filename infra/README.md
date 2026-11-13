# Infrastructure

Service configuration for the local lab; `compose.yaml` at the repository root references these files so plain `docker compose` works without `-f`.
See [DECISIONS §3](../docs/DECISIONS.md#3-docker-compose) and the [Phase 0 plan](../docs/plans/phase-00-repository-and-infrastructure.md).

| Path | Purpose |
| --- | --- |
| `clickhouse/config.d/listen.xml` | Listen on container interfaces; Compose publishes ports on host loopback only |
| `clickhouse/config.d/sources.xml` | One named collection per data source, named after its manifest, reading the source's read-only credentials from the environment |
| `clickhouse/users.d/users.xml` | Removes the passwordless `default` user |
| `clickhouse/users.d/agent_logs.xml` | Insert-only `agent_logs_writer`, trace reader and review reader users for `agent_logs` |
| `clickhouse/users.d/agent_query_stopper.xml` | `agent_query_stopper`, which may only list and stop running queries; the api stops the query of an answer whose client disconnected |
| `clickhouse/users.d/model_tiers.xml` | `model_tiers_admin`, which reads the eval reports and records the admin actions of the Models page, and reads the tier mapping of the LiteLLM Proxy era once |
| `clickhouse/users.d/sources.xml` | `source_loader`, the only user that may use the source named collections; copies sources into `raw` and defines the live `src_<source>` databases |
| `clickhouse/changes/0001_databases.sql` | Creates `raw`, `marts` and `data_meta` |
| `clickhouse/changes/0002_agent_logs.sql` | Creates the `agent_logs` database and its run log tables |
| `clickhouse/changes/0003_model_tiers.sql` | Creates `data_meta.model_tiers`, the tier mapping of the LiteLLM Proxy era, which the api copies into its app state once |
| `clickhouse/changes/0004_documents.sql` | Creates `data_meta.documents`, the registry of company documents |
| `sources/fixtures/` | Lab-only fixture source systems of the `sources` Compose profile: the synthetic widget dataset (`widgets/`, written by `generate.py`) and one seed script per PostgreSQL, MySQL, MongoDB and the S3-compatible store |
| `keycloak/realm-finch.json` | Realm `finch`: the active pack's policy roles and the console roles `pack_reviewer` and `admin`, one lab user per role without credentials, the public `finch-web` client whose access tokens carry the realm roles and the api audience, and the lab-only `finch-cli` password-grant client |

## ClickHouse users and databases

The image entrypoint creates the admin user from `CLICKHOUSE_ADMIN_USER` and `CLICKHOUSE_ADMIN_PASSWORD`.
The files in `clickhouse/changes/` are numbered schema changes (`NNNN_name.sql`, no gaps). The ClickHouse entrypoint runs them only when the `clickhouse-data` volume is empty; `jobs.migrate` applies the ones a volume has not recorded in `data_meta.schema_changes`, so a fresh volume and an older one end at the same version. ClickHouse has no transactional DDL, so every change must be idempotent (`CREATE ... IF NOT EXISTS`, `ADD COLUMN IF NOT EXISTS`). Never edit a change that has shipped; add the next number.

```bash
docker compose run --rm jobs python -m jobs.migrate
```

A second run applies nothing. A volume that records a change this version does not know was written by a newer image and is refused.

## Data directory and secret key

`FITCHER_DATA_DIR` (default `/data`) is the single root of persistent application files. In Compose the named volume `fitcher-data` is mounted there for `api` and `jobs`.

| File | Purpose |
| --- | --- |
| `app.db` | The app state in SQLite (settings, encrypted secrets, setup state); numbered changes live in `apps/api/app/state/changes/` and are recorded in its `schema_changes` table. The api and `jobs.migrate` apply them |
| `secret.key` | The instance key that encrypts stored secrets (AES-256-GCM), generated on first use with mode 0600 |

`FITCHER_SECRET_KEY` (base64 of 32 random bytes, for example `openssl rand -base64 32`) replaces `secret.key` when set. Losing the key makes stored secrets unreadable, so the data volume is the backup unit; if `secret.key` is missing while secrets exist, the api refuses to start instead of generating a new key. SQLite can corrupt on a network file system, so the data volume must be a local disk.

Changing the admin password in `.env` after the first start also needs only a container recreate, because the entrypoint rewrites the user file on every start.

The agent runs every generated query as the ClickHouse user of the asking role, `fitcher_agent__<pack>__<role>`.
`compile_pack` creates these users, their roles, column grants, row policies, aggregate-only views and the shared read-only profile from the pack's `policies.yaml` (see [packs/](../packs/README.md#compiling-a-pack)); they live in the data volume and are reconciled on every compile.
Their passwords derive from `CLICKHOUSE_AGENT_PASSWORD`; after changing it, run `compile_pack` again.

Run logs live in `agent_logs`. On a volume created before one of the `clickhouse/changes/` files existed, or before one of their tables or columns was added, create what is missing with `docker compose run --rm jobs python -m jobs.migrate`.
Six configuration users reach it and the registries in `data_meta`, each with its own password:

| User | Password | Access |
| --- | --- | --- |
| `agent_logs_writer` | `CLICKHOUSE_LOGS_WRITER_PASSWORD` | `INSERT` on `agent_logs`; no reads |
| `agent_logs_trace_reader` | `CLICKHOUSE_TRACE_READER_PASSWORD` | `SELECT` on `runs`, `events`, `llm_calls`, `sql_runs`, `audit`, `eval_reports`, `input_screening`, `conversations`, `chat_messages` and `system.query_log` for the `admin` paths |
| `agent_logs_review_reader` | `CLICKHOUSE_REVIEW_READER_PASSWORD` | `SELECT` on `example_proposals`, `feedback`, `chat_messages`, `runs`, `events` and `sql_runs` for the `pack_reviewer` paths and the proposals built from runs |
| `agent_conversations` | `CLICKHOUSE_CONVERSATIONS_PASSWORD` | `SELECT` and `INSERT` on `chat_messages`, `conversations` and `conversation_groups`; the api's conversation store, which filters every query by the requesting user |
| `model_tiers_admin` | `CLICKHOUSE_MODEL_TIERS_PASSWORD` | `SELECT` and `INSERT` on `data_meta.model_tiers`, `SELECT` on `eval_reports` and `INSERT` on `admin_actions`; the Models page's eval results and admin actions, and the one-time copy of the old tier mapping |
| `pack_review` | `CLICKHOUSE_PACK_REVIEW_PASSWORD` | `SELECT` and `INSERT` on the document registry `data_meta.documents` and `SELECT` on `marts`; the api's Documents and Review paths, whose test-runs send `readonly=2` and the `QUERY_MAX_*` limits |

The agent's role users have no access to `agent_logs`.
With the stack running, `AGENT_LOGS_LIVE_TEST=1` and the seven passwords in the environment, `jobs/tests/test_agent_log_users.py` checks these grants against the server.

### Data sources

Source credentials reach ClickHouse only: `config.d/sources.xml` defines one named collection per source manifest whose values come from the clickhouse service's environment, and `system.named_collections` hides them.
`source_loader` (`CLICKHOUSE_SOURCES_PASSWORD`) is the only user granted the collections; it may create, fill, exchange and drop tables in `raw` and create the `src_*` databases and their table engines.
ClickHouse requires `INSERT` to create a table on a writable engine, so it holds `INSERT` on `src_*`; the source system's read-only user still refuses every write.
The admin and dbt read `src_*` tables without the collections, and live marts are views that run with their definer's privileges, so no agent role is granted `raw` or `src_*`.
Adding a source and choosing its mode are described in [jobs/](../jobs/README.md#data-sources).

The `sources` Compose profile starts the fixture systems `postgres-fixture`, `mysql-fixture`, `mongodb-fixture` and `files-fixture` (SeaweedFS), which publish no port.
PostgreSQL, MySQL and MongoDB seed on a fresh volume, so recreate one with `docker compose --profile sources rm -sfv <service>` to seed it again; the file store empties its volume and copies the files on every start.

## Models

There is no model gateway service: the api and the jobs call every provider in process through the LiteLLM SDK (`apps/api/app/llm/gateway.py`, DECISIONS §2). Providers, their keys and the model of each tier are kept in the app state of the `fitcher-data` volume and managed in the setup and on the Models page; `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY` and `OLLAMA_URL` only create the first providers on a start that finds none.
The embed tier uses the first connected provider's embedding model; with none, or when an admin chooses it, a local fastembed model downloaded on first use into `/data/models`.
For a local chat model, start `docker compose --profile local-models up -d --wait ollama`, pull a model with `docker compose exec ollama ollama pull <model>` and add an Ollama provider with the base URL `http://ollama:11434` (or `http://host.docker.internal:11434` for a model server on the host).
Every call, answered, failed or refused, is written to `agent_logs.llm_calls` with its tier, provider, model, tokens, estimated cost, latency and error; inside a traced run it carries the run's `trace_id` and graph node.
The gateway refuses a call without `screening` metadata and reruns the EN/VI rules of `apps/api/app/screening/rules.py` on every message and embedding input before any provider call (DECISIONS §9); it closes code paths that forgot to screen and is not an authentication boundary.

## Keycloak

Keycloak runs `start-dev` with its embedded development database and imports `realm-finch.json` when the realm does not exist.
Edits to the realm file apply after `docker compose up -d --force-recreate --wait keycloak`, which starts from a new container.

The realm roles equal the roles of the active pack's `policies.yaml` plus `pack_reviewer` and `admin`; a test fails when they drift, so a pack role change also edits this file.
The lab users (`lab.analyst`, `lab.marketing`, `lab.northwest`, `lab.partner`, `lab.reviewer`, `lab.admin`) are tracked without passwords; after every import set them from `KEYCLOAK_LAB_USER_PASSWORD` in `.env`:

```bash
docker compose run --rm jobs python -m jobs.set_lab_passwords
```

Each user has a verified `@fitcher.test` email, so the first sign-in asks for no profile update.
`finch-web` access tokens carry the user's roles under `realm_access.roles`.
Access tokens of `finch-web` and of the lab-only `finch-cli` client name `finch-api` as audience, which the api requires (`KEYCLOAK_AUDIENCE`).
The confidential `fitcher-admin-api` client has no browser flow; its service account holds only the `realm-management` roles `view-users` and `manage-users`, which the api uses for the console's Users section, and its secret is `KEYCLOAK_ADMIN_API_SECRET` in `.env`.
A role change made there applies when the user's access token is next issued: at the next sign-in or token refresh, within the realm's access token lifespan.
`finch-web` redirects only to the web app's `/auth/callback`; `finch-cli` has no browser flow and grants tokens for a lab user's username and password, for curl against the api.
`KC_HOSTNAME` fixes the issuer to `http://localhost:8080/realms/finch` (`KEYCLOAK_ISSUER`) whichever address requested a token, while containers keep reaching Keycloak at `keycloak:8080`; the api reads the signing keys from `KEYCLOAK_JWKS_URL`.
