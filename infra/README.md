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
| `dev/accounts.yaml` | Development accounts of the development packs (one per pack role and console role), created in team mode by `jobs.seed_dev_accounts` with `DEV_ACCOUNT_PASSWORD` from `.env`; never in the released image |

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

A source connected on the Sources page (DECISIONS §4, §15) keeps its credentials in a named collection created with SQL and stored encrypted by ClickHouse: `config.d/named_collections_storage.xml` selects the `local_encrypted` storage under `/var/lib/clickhouse/named_collections` with the key in `CLICKHOUSE_NAMED_COLLECTIONS_KEY` (64 hex characters).
The release image renders the same setting with a key derived from the instance key (`jobs/init_data.py`), so the key is as safe as `/data/secret.key`; changing or losing it makes the stored collections unreadable and the sources must be connected again.
The api connects as `source_admin` (`CLICKHOUSE_SOURCE_ADMIN_PASSWORD`), which may create, alter, drop and use named collections but holds no `SHOW NAMED COLLECTIONS SECRETS` grant, so no query returns a password; ClickHouse writes `CREATE` and `ALTER NAMED COLLECTION` to its query log and server log with every value hidden.
`source_admin` also creates the `src_*` databases, writes `raw` and sees the definitions of `marts` (`SHOW TABLES`, never data) so that a source read by a mart is not deleted.
An existing ClickHouse server needs `source_admin.xml` and `named_collections_storage.xml` mounted and a restart; nothing else changes, because no collection created with SQL existed before.

The SQL Server fixture (`sqlserver-fixture` in the `sources` profile) is the vendor's `mcr.microsoft.com/mssql/server` image: amd64 only, about 2 GB of memory, and starting it accepts Microsoft's licence terms (`ACCEPT_EULA`). It is seeded by `infra/sources/sqlserver/init.sh` and is never part of the release image. A SQL Server source connected in the application is not a named collection: the api reads it with `pymssql` and keeps its password in the app state's encrypted secrets (DECISIONS §4).

Source credentials of the development manifests reach ClickHouse only: `config.d/sources.xml` defines one named collection per source manifest whose values come from the clickhouse service's environment, and `system.named_collections` hides them.
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

## Sign-in

Sign-in is built into the api (DECISIONS §9); no service runs for it.
Individual mode answers only on localhost and the names of `FITCHER_ALLOWED_HOSTS`; Compose also sets `FITCHER_INTERNAL_HOSTS=api`, the name by which the web service reaches the api, which the web server sends with the browser's own host as `X-Forwarded-Host`.
Team mode keeps accounts and sessions in the app state. For development, create the accounts of `dev/accounts.yaml` and put the instance in team mode:

```bash
docker compose run --rm jobs python -m jobs.seed_dev_accounts
```

A second run resets their passwords, roles and status. Their ids are the usernames the development users had under Keycloak, so their conversations and run logs stay theirs.
An admin may register one OpenID Connect provider with `PUT /settings/oidc`; register `http://localhost:3000/auth/oidc/callback` (or the instance's public address) as its redirect URI.

## Release image

The root `Dockerfile` builds the one-container image of DECISIONS §3; [docs/install.md](../docs/install.md) is its user guide.

| Path | Purpose |
| --- | --- |
| `image/s6-rc.d/` | s6-overlay services: `init-data` and `migrate` (oneshots), `clickhouse`, `qdrant`, `api` and `web` |
| `image/user-bundles.d/user/` | The bundle s6-overlay starts, listing every service |
| `image/scripts/` | `init-data` (runs `jobs.init_data`), `migrate` (waits for ClickHouse, then runs `jobs.migrate` as its admin) and `finish`, which stops the container after five exits of one service within a minute |
| `image/clickhouse/users.d/admin.xml` | The embedded server's administrator `fitcher_admin`; `jobs.init_data` renders it and `clickhouse/users.d/` with password hashes on every start |
| `image/healthcheck.sh` | The image healthcheck: web, api and ClickHouse must all answer |
| `image/fitcher` | `docker exec <container> fitcher <job> [args]` runs a job module with the admin environment |

`../deploy/compose.external-clickhouse.yaml` runs the image against a separate ClickHouse server through `CLICKHOUSE_URL`.
