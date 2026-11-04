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
| `clickhouse/users.d/model_tiers.xml` | `model_tiers_admin`, which reads and writes the model tier mapping, reads eval reports and records admin actions for the Models page |
| `clickhouse/users.d/sources.xml` | `source_loader`, the only user that may use the source named collections; copies sources into `raw` and defines the live `src_<source>` databases |
| `clickhouse/initdb/001-databases.sql` | Creates `raw`, `marts` and `data_meta` |
| `clickhouse/initdb/010-agent-logs.sql` | Creates the `agent_logs` database and its run log tables |
| `clickhouse/initdb/020-model-tiers.sql` | Creates `data_meta.model_tiers`, the model tier mapping of the Models page |
| `litellm/config.yaml` | Gateway settings shared by every model: callbacks, guardrail and master key |
| `litellm/catalog/*.yaml` | One file per provider (OpenAI, Anthropic, Gemini, Ollama) with its aliases, named `<provider>-<size>`, and the variables it needs |
| `litellm/build_config.py` | Container entrypoint: adds each catalog file whose variables are set to the settings and starts the proxy |
| `litellm/callbacks/clickhouse_logger.py` | Proxy callback writing one `agent_logs.llm_calls` row per call as `agent_logs_writer` |
| `litellm/callbacks/screening_guard.py` | `pre_call` guardrail rejecting requests without the api's `screening` metadata and rerunning the EN/VI rules |
| `litellm/callbacks/screening_rules.py` | Byte-identical copy of `apps/api/app/screening/rules.py` for the guardrail |
| `sources/fixtures/` | Lab-only fixture source systems of the `sources` Compose profile: the synthetic widget dataset (`widgets/`, written by `generate.py`) and one seed script per PostgreSQL, MySQL, MongoDB and the S3-compatible store |
| `keycloak/realm-finch.json` | Realm `finch`: the active pack's policy roles and the console roles `pack_reviewer` and `admin`, one lab user per role without credentials, the public `finch-web` client whose access tokens carry the realm roles and the api audience, and the lab-only `finch-cli` password-grant client |

## ClickHouse users and databases

The image entrypoint creates the admin user from `CLICKHOUSE_ADMIN_USER` and `CLICKHOUSE_ADMIN_PASSWORD`.
Scripts in `initdb/` run only when the `clickhouse-data` volume is empty.
The script is idempotent; apply it to an existing volume with:

```bash
docker compose exec -T clickhouse sh -c 'clickhouse-client --user "$CLICKHOUSE_USER" --password "$CLICKHOUSE_PASSWORD" --queries-file /docker-entrypoint-initdb.d/001-databases.sql'
```

Changing the admin password in `.env` after the first start also needs only a container recreate, because the entrypoint rewrites the user file on every start.

The agent runs every generated query as the ClickHouse user of the asking role, `fitcher_agent__<pack>__<role>`.
`compile_pack` creates these users, their roles, column grants, row policies, aggregate-only views and the shared read-only profile from the pack's `policies.yaml` (see [packs/](../packs/README.md#compiling-a-pack)); they live in the data volume and are reconciled on every compile.
Their passwords derive from `CLICKHOUSE_AGENT_PASSWORD`; after changing it, run `compile_pack` again.

Run logs live in `agent_logs`. On a volume created before `010-agent-logs.sql` or `020-model-tiers.sql` existed, or before one of their tables or columns was added, create what is missing with `docker compose run --rm jobs python -m jobs.apply_log_schema`.
Five configuration users reach it, each with its own password:

| User | Password | Access |
| --- | --- | --- |
| `agent_logs_writer` | `CLICKHOUSE_LOGS_WRITER_PASSWORD` | `INSERT` on `agent_logs`; no reads |
| `agent_logs_trace_reader` | `CLICKHOUSE_TRACE_READER_PASSWORD` | `SELECT` on `runs`, `events`, `llm_calls`, `sql_runs`, `audit`, `eval_reports` and `system.query_log` |
| `agent_logs_review_reader` | `CLICKHOUSE_REVIEW_READER_PASSWORD` | `SELECT` on `example_proposals`, `feedback` and `chat_messages` for the `pack_reviewer` and `admin` paths |
| `agent_conversations` | `CLICKHOUSE_CONVERSATIONS_PASSWORD` | `SELECT` and `INSERT` on `chat_messages`, `conversations` and `conversation_groups`; the api's conversation store, which filters every query by the requesting user |
| `model_tiers_admin` | `CLICKHOUSE_MODEL_TIERS_PASSWORD` | `SELECT` and `INSERT` on `data_meta.model_tiers`, `SELECT` on `eval_reports` and `INSERT` on `admin_actions`; the api's tier lookup and Models page |

The agent's role users have no access to `agent_logs`.
With the stack running, `AGENT_LOGS_LIVE_TEST=1` and the six passwords in the environment, `jobs/tests/test_agent_log_users.py` checks these grants against the server.

### Data sources

Source credentials reach ClickHouse only: `config.d/sources.xml` defines one named collection per source manifest whose values come from the clickhouse service's environment, and `system.named_collections` hides them.
`source_loader` (`CLICKHOUSE_SOURCES_PASSWORD`) is the only user granted the collections; it may create, fill, exchange and drop tables in `raw` and create the `src_*` databases and their table engines.
ClickHouse requires `INSERT` to create a table on a writable engine, so it holds `INSERT` on `src_*`; the source system's read-only user still refuses every write.
The admin and dbt read `src_*` tables without the collections, and live marts are views that run with their definer's privileges, so no agent role is granted `raw` or `src_*`.
Adding a source and choosing its mode are described in [jobs/](../jobs/README.md#data-sources).

The `sources` Compose profile starts the fixture systems `postgres-fixture`, `mysql-fixture`, `mongodb-fixture` and `files-fixture` (SeaweedFS), which publish no port.
PostgreSQL, MySQL and MongoDB seed on a fresh volume, so recreate one with `docker compose --profile sources rm -sfv <service>` to seed it again; the file store keeps no volume and copies the files on every start.

## LiteLLM

The engine calls a model tier; the api maps it to a catalog alias (DECISIONS §2 Model tiers). The proxy starts through `build_config.py`, which loads a provider's aliases only when its variables are set (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, `OLLAMA_URL`); with none it starts with an empty catalog and stays healthy. Add or change a model in its `catalog/` file and run `docker compose up -d --wait litellm`; a new alias serves a tier only after `make smoke` and a passing eval with `--tier`.
The proxy requires `LITELLM_MASTER_KEY`; the provider keys reach only this container.
For a local model, start `docker compose --profile local-models up -d --wait ollama`, pull the model named in `catalog/ollama.yaml` with `docker compose exec ollama ollama pull <model>`, set `OLLAMA_URL=http://ollama:11434` and restart litellm. The profile is off by default; the model needs several GB of RAM and disk.
Every call, successful or failed, is written to `agent_logs.llm_calls` with its alias, tier, resolved model, tokens, cost, latency and error; the api's `trace_id`, graph node and tier arrive as request `metadata`, and calls outside a traced run have an empty trace id. A failed write is printed to the proxy log and never affects the reply.

The `screening-guard` guardrail runs before every call (DECISIONS §9). A request whose metadata has no `screening` value of `allow`, `flag` or `trusted_pack` is rejected with HTTP 400 `screening_guard: ...`, and so is one whose messages or embedding inputs trip the EN/VI rules; the api turns that rejection into the `blocked` reply. It closes code paths that forgot to screen and is not an authentication boundary. Change a rule in `apps/api/app/screening/rules.py`, copy the file over `callbacks/screening_rules.py` and restart litellm; a test fails while the copies differ.

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
`finch-web` redirects only to the web app's `/auth/callback`; `finch-cli` has no browser flow and grants tokens for a lab user's username and password, for curl against the api.
`KC_HOSTNAME` fixes the issuer to `http://localhost:8080/realms/finch` (`KEYCLOAK_ISSUER`) whichever address requested a token, while containers keep reaching Keycloak at `keycloak:8080`; the api reads the signing keys from `KEYCLOAK_JWKS_URL`.
