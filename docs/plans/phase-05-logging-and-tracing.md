# Phase 5: Logging and tracing

## Goal

Make every run traceable: all nodes, LLM calls, SQL executions and ClickHouse query-log rows for one `trace_id` can be retrieved with a single SQL query on `agent_logs`.

## Scope

- ClickHouse database `agent_logs` with the seven tables of DECISIONS §10, a dedicated user and 90-day TTL.
- An async batched log writer inside the api process.
- LiteLLM callback writing `llm_calls`.
- A trace view joining `system.query_log` through `log_comment`.
- Eval reports stored in `agent_logs`.

## Out of scope

- `audit` decisions beyond the table definition (Phase 6 writes them).
- `chat_messages` reads for follow-ups (Phase 8) and `feedback` writes (Phase 9); tables are created now.
- Admin UI (Phase 12).

## Prerequisites

- Phase 3 graph with `trace_id` in state and `log_comment` on execution.

## Deliverables

```text
infra/clickhouse/
  initdb/010-agent-logs.sql         # fresh volumes
  users.d/agent_logs_writer.xml     # insert-only user for logs
jobs/apply_log_schema.py            # idempotent apply for existing volumes
apps/api/app/observability/
  tracing.py                        # OpenTelemetry setup, trace_id helpers
  log_writer.py                     # bounded async queue, batch flush
  events.py                         # typed log records per table
infra/litellm/callbacks/clickhouse_logger.py   # or built-in integration, see open question 1
```

## Tasks

1. **Schema.** `runs`, `events`, `llm_calls`, `sql_runs`, `audit`, `chat_messages`, `feedback`, plus `eval_reports`. MergeTree, `TTL ts + INTERVAL 90 DAY`, `ORDER BY (trace_id, ts)` for trace tables and `(user_id, ts)` for user tables. The same DDL serves `initdb` and the idempotent apply job (`CREATE ... IF NOT EXISTS`).
2. **Users.** `agent_logs_writer` may only insert into `agent_logs`; a read user for traces may select from `agent_logs` and `system.query_log`. The read-only agent user from Phase 3 gets no access to `agent_logs`.
3. **Tracing.** OpenTelemetry SDK creates a span per run and per node; `trace_id` is the 32-hex span trace id, carried in graph state.
4. **Log writer (test first).** Tests: records flush at batch size and at interval, flush on shutdown, bounded queue drops oldest records and counts drops instead of blocking the request, writer failure never fails the run.
5. **Node instrumentation.** A wrapper records start, end, status and a size-capped payload for each node without changing node signatures.
6. **SQL runs.** Every execute attempt writes SQL, `query_id`, rows, error and attempt number.
7. **LLM calls.** The api sends `trace_id` and node name as LiteLLM request metadata; the callback writes alias, resolved model, tokens, cost and error to `llm_calls`.
8. **Trace view.** `agent_logs.trace_query_log` joins `system.query_log` on `log_comment = trace_id`; a documented query returns the full trace.
9. **Eval reports.** `eval.py` writes its JSON report to `eval_reports`.

## Contracts

- Log record schemas in `events.py` match the table columns.
- Config: `CLICKHOUSE_LOGS_WRITER_PASSWORD`, `LOG_BATCH_SIZE`, `LOG_FLUSH_INTERVAL_MS`, `LOG_QUEUE_MAX`.

## Verification

```bash
uv run --project apps/api pytest -c apps/api/pyproject.toml
docker compose run --rm api python -m jobs.apply_log_schema
docker compose run --rm api python -m jobs.ask "<acceptance question>"
docker compose exec clickhouse clickhouse-client --query "<trace query with the printed trace_id>"
```

## Definition of done

| DoD item | Proof |
|---|---|
| One SQL query returns nodes, LLM calls, SQL and query_log for a trace | Query and its output in the PR |

## Risks and open questions

1. **LiteLLM callback mechanism.** Default: use a custom callback module mounted into the LiteLLM container if the built-in ClickHouse logger does not match the `llm_calls` schema; verify against the pinned LiteLLM version.
2. **query_log delay.** `system.query_log` flushes periodically (seconds); trace queries run immediately after a run may miss rows. Document and, in tests, call `SYSTEM FLUSH LOGS` as admin.
3. **Payload size and privacy.** Default: payloads are truncated to 16 KB; result rows are not logged, only counts.
4. **Eval report storage.** DECISIONS §10 lists seven tables while §12 stores eval reports in `agent_logs`. Default: an eighth table `eval_reports`; DECISIONS §10 is updated in the same PR if the owner agrees.
5. **Existing volumes.** `initdb` runs only on fresh volumes, so `apply_log_schema` is mandatory for existing ones.

## Branch and PR split

- `feat/db/create-agent-log-tables`: tasks 1-2.
- `feat/api/trace-agent-runs`: tasks 3-9.
