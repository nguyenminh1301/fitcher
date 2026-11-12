# Tracing an agent run

Every agent run writes what it did to the ClickHouse database `agent_logs` ([DECISIONS §10](DECISIONS.md#10-logging-clickhouse-agent_logs)).
The trace id printed by `jobs.ask` (and kept per case in an eval JSON report) is the OpenTelemetry trace id of the run, and it ties together every record of the run.

| Source | Written by | One row per |
| --- | --- | --- |
| `runs` | api, synchronously before and after the graph | run state (`running`, then `succeeded`, `failed`, `rejected` or `error`); read with `FINAL` |
| `events` | api log writer | graph node execution, with a JSON payload capped at 16 KB and result rows reduced to counts |
| `sql_runs` | api log writer | executed query, with its `query_id` |
| `llm_calls` | LiteLLM proxy callback | gateway call, with catalog alias, model tier, resolved model, tokens and cost |
| `trace_query_log` | view over `system.query_log` | query ClickHouse ran with `log_comment = trace_id` |

## The full trace in one query

[`infra/clickhouse/queries/trace.sql`](../infra/clickhouse/queries/trace.sql) returns all five sources for one trace, ordered by time:

```bash
docker compose exec -T clickhouse sh -c 'clickhouse-client --user agent_logs_trace_reader --password "$CLICKHOUSE_TRACE_READER_PASSWORD" --param_trace_id=<trace id> --format PrettyCompactMonoBlock --queries-file /dev/stdin' < infra/clickhouse/queries/trace.sql
```

## Reading the result

- The `run` row's `state` is `complete` only when `log_complete` is true: the running row and every queued record of the run reached ClickHouse.
- `INCOMPLETE` means a record was lost (queue full, a batch failed three attempts, or the end-of-run flush timed out), a run-row write failed, or the run never wrote its final row. Its detail names the lost record count. The api prints the trace id and error of each failed write to stderr.
- `llm_calls_sent` counts the gateway requests the api sent; `llm_calls_logged` counts the rows the LiteLLM callback wrote. A difference means callback writes failed (see the `litellm` service log), since those rows are not part of `log_complete`.
- `system.query_log` is flushed every few seconds, so a trace read right after its run may miss its last queries. Run `SYSTEM FLUSH LOGS` as the ClickHouse admin first when the query log matters.

Rows expire after 90 days. On a volume created before the tables existed, create them with `docker compose run --rm jobs python -m jobs.migrate`.
