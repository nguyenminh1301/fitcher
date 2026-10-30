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

1. **Schema.** `runs`, `events`, `llm_calls`, `sql_runs`, `audit`, `chat_messages`, `feedback`, plus `eval_reports` and, for Phase 12, `example_proposals` (`ORDER BY (pack, ts)`, readable only by the `pack_reviewer` and `admin` read paths). MergeTree, `TTL ts + INTERVAL 90 DAY`, `ORDER BY (trace_id, ts)` for trace tables and `(user_id, ts)` for user tables. The same DDL serves `initdb` and the idempotent apply job (`CREATE ... IF NOT EXISTS`).
2. **Users.** `agent_logs_writer` may only insert into `agent_logs`. The trace read user gets table-level `SELECT` on the trace tables (`runs`, `events`, `llm_calls`, `sql_runs`, `audit`, `eval_reports`) and `system.query_log` only; a separate review read user selects `example_proposals`, `feedback` and `chat_messages` for the `pack_reviewer` and `admin` paths. A negative test proves the trace reader cannot select `example_proposals`. The read-only agent user from Phase 3 gets no access to `agent_logs`.
3. **Tracing.** OpenTelemetry SDK creates a span per run and per node; `trace_id` is the 32-hex span trace id, carried in graph state.
4. **Log writer (test first).** `runs` is a ReplacingMergeTree keyed by `trace_id`: the api writes a `running` row synchronously before the graph starts and a final row synchronously after it ends, so the completeness marker never depends on the batch queue; if either synchronous write fails, the api writes the trace id and error to its stderr log. Other records flush at batch size, at interval and on shutdown. At the end of each run the api awaits the flush of that run's records with a bounded timeout, and failed batches are retried a bounded number of times with a stable batch identity (ClickHouse insert deduplication token), so a retry of a batch that was already written adds no rows. If the queue overflows, a flush times out or ClickHouse rejects a batch, the run still returns its answer, but its `runs` row records `log_complete = false` and the number of lost records. `log_complete` covers only records the api writes (`runs`, `events`, `sql_runs`, `audit`); `llm_calls` rows come from the LiteLLM callback and are reconciled by the trace query, which reports how many LLM calls the api made versus how many rows exist. Tests cover each path, a failure of the first batch, a retried batch that was already written, and that `log_complete` is true only when every api record of the run was written.
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
docker compose run --rm api python -m jobs.eval --pack ecommerce_twin --baseline packs/ecommerce_twin/eval_baseline.json
```

## Definition of done

| DoD item | Proof |
|---|---|
| One SQL query returns nodes, LLM calls, SQL and query_log for a trace | Query and output in the PR for a run with `log_complete = true`; incomplete runs are flagged, never presented as complete |
| No agent regression | Eval report and baseline diff attached to the PR |

## Risks and open questions

1. **LiteLLM callback mechanism.** Default: use a custom callback module mounted into the LiteLLM container if the built-in ClickHouse logger does not match the `llm_calls` schema; verify against the pinned LiteLLM version.
2. **query_log delay.** `system.query_log` flushes periodically (seconds); trace queries run immediately after a run may miss rows. Document and, in tests, call `SYSTEM FLUSH LOGS` as admin.
3. **Payload size and privacy.** Default: payloads are truncated to 16 KB; result rows are not logged, only counts.
4. **Eval report storage.** DECISIONS §10 lists seven tables while §12 stores eval reports in `agent_logs`. Default: an eighth table `eval_reports`; DECISIONS §10 is updated in the same PR if the owner agrees.
5. **Existing volumes.** `initdb` runs only on fresh volumes, so `apply_log_schema` is mandatory for existing ones.

## Branch and PR split

- `feat/db/create-agent-log-tables`: tasks 1-2.
- `feat/api/trace-agent-runs`: tasks 3-9.
