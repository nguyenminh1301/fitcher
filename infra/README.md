# Infrastructure

Service configuration for the local lab; `compose.yaml` at the repository root references these files so plain `docker compose` works without `-f`.
See [DECISIONS §3](../docs/DECISIONS.md#3-docker-compose) and the [Phase 0 plan](../docs/plans/phase-00-repository-and-infrastructure.md).

| Path | Purpose |
| --- | --- |
| `clickhouse/config.d/listen.xml` | Listen on container interfaces; Compose publishes ports on host loopback only |
| `clickhouse/users.d/users.xml` | Removes the passwordless `default` user |
| `clickhouse/users.d/agent_readonly.xml` | Read-only `agent_readonly` user and profile the agent runs generated SQL as |
| `clickhouse/users.d/agent_logs.xml` | Insert-only `agent_logs_writer`, trace reader and review reader users for `agent_logs` |
| `clickhouse/initdb/001-databases.sql` | Creates `raw`, `marts` and `data_meta` |
| `clickhouse/initdb/010-agent-logs.sql` | Creates the `agent_logs` database and its run log tables |
| `litellm/config.yaml` | Aliases `fast`, `sql-gen`, `sql-gen-hard` and `embed`, with models from `LITELLM_MODEL_*` |
| `litellm/callbacks/clickhouse_logger.py` | Proxy callback writing one `agent_logs.llm_calls` row per call as `agent_logs_writer` |
| `keycloak/realm-finch.json` | Realm `finch` with the public `finch-web` client and no users |
| `opensearch/` | Host requirements; no custom JVM or plugin settings |

## ClickHouse users and databases

The image entrypoint creates the admin user from `CLICKHOUSE_ADMIN_USER` and `CLICKHOUSE_ADMIN_PASSWORD`.
Scripts in `initdb/` run only when the `clickhouse-data` volume is empty.
The script is idempotent; apply it to an existing volume with:

```bash
docker compose exec -T clickhouse sh -c 'clickhouse-client --user "$CLICKHOUSE_USER" --password "$CLICKHOUSE_PASSWORD" --queries-file /docker-entrypoint-initdb.d/001-databases.sql'
```

Changing the admin password in `.env` after the first start also needs only a container recreate, because the entrypoint rewrites the user file on every start.

The agent runs every generated query as `agent_readonly`, whose password is `CLICKHOUSE_AGENT_PASSWORD`.
It holds only `SELECT` on `marts`; its profile sets `readonly = 2` (reads only, while each query may set its own limits) and constrains `max_execution_time`, `max_result_rows` and `max_memory_usage`.
The user lives in server configuration, not in the data volume, so it applies to new and existing volumes alike; recreate the container after changing the file or the password: `docker compose up -d --wait clickhouse`.

Run logs live in `agent_logs`. On a volume created before `010-agent-logs.sql` existed, create its tables with `docker compose run --rm jobs python -m jobs.apply_log_schema`.
Three configuration users reach it, each with its own password:

| User | Password | Access |
| --- | --- | --- |
| `agent_logs_writer` | `CLICKHOUSE_LOGS_WRITER_PASSWORD` | `INSERT` on `agent_logs`; no reads |
| `agent_logs_trace_reader` | `CLICKHOUSE_TRACE_READER_PASSWORD` | `SELECT` on `runs`, `events`, `llm_calls`, `sql_runs`, `audit`, `eval_reports` and `system.query_log` |
| `agent_logs_review_reader` | `CLICKHOUSE_REVIEW_READER_PASSWORD` | `SELECT` on `example_proposals`, `feedback` and `chat_messages` for the `pack_reviewer` and `admin` paths |

`agent_readonly` has no access to `agent_logs`.
With the stack running, `AGENT_LOGS_LIVE_TEST=1` and the four passwords in the environment, `jobs/tests/test_agent_log_users.py` checks these grants against the server.

## LiteLLM

Change a model by editing its `LITELLM_MODEL_*` value in `.env` and running `docker compose up -d --wait litellm`.
The proxy requires `LITELLM_MASTER_KEY`; `OPENAI_API_KEY` reaches only this container.
Every call, successful or failed, is written to `agent_logs.llm_calls` with its alias, resolved model, tokens, cost, latency and error; the api's `trace_id` and graph node arrive as request `metadata`, and calls outside a traced run have an empty trace id. A failed write is printed to the proxy log and never affects the reply.

## Keycloak

Keycloak runs `start-dev` with its embedded development database and imports `realm-finch.json` when the realm does not exist.
Edits to the realm file apply after `docker compose up -d --force-recreate --wait keycloak`, which starts from a new container.
