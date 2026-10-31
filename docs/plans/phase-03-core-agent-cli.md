# Phase 3: Core agent on the CLI

## Goal

Run the `data_query` flow end to end from the command line: `jobs/ask.py "<question>"` extracts the request, resolves time, retrieves context, builds a QuerySpec, generates and guards SQL, executes it on ClickHouse with self-repair, shapes the result and summarizes it.

## Scope

- LangGraph graph with nodes `extract`, `resolve_time`, `retrieve`, `build_spec`, `generate_sql`, `guard`, `explain`, `execute`, `check`, `shape_result`, `summarize` (DECISIONS §6 steps 4-16, without router, gate branches or chart_recommender).
- Pydantic contracts `QuerySpec` and `Result` (DECISIONS §7).
- One read-only ClickHouse user for all queries.
- `jobs/ask.py` is a fail-closed `data_query` entry point: without router and gate, it rejects questions whose extraction has no metric, no resolvable period or several equally likely metrics, before `generate_sql` runs.
- A repository check that `apps/api` contains no pack table or metric name.

## Out of scope

- Router, clarify/deny branches, follow-ups (Phases 6 and 8).
- Per-role users, row policies and role allowlists (Phase 6); guard uses the full approved catalog.
- Logging to `agent_logs` (Phase 5), HTTP/SSE (Phase 7), charts (Phase 9).

## Prerequisites

- Phase 2 compiled pack and indices; Phase 1 marts.

## Deliverables

```text
apps/api/app/
  contracts/query_spec.py result.py
  llm/client.py                     # LLMClient protocol + LiteLLM implementation
  agent/state.py graph.py
  agent/nodes/extract.py resolve_time.py retrieve.py build_spec.py
              generate_sql.py guard.py explain.py execute.py check.py
              shape_result.py summarize.py
  data/clickhouse.py                # query runner with settings and query_id
apps/api/prompts/
  extract.v1.md generate_sql.v1.md summarize.v1.md
infra/clickhouse/users.d/agent_readonly.xml
jobs/ask.py
scripts/check_pack_isolation.py
```

## Tasks

1. **Contracts.** `QuerySpec`, `Period`, `Filter`, `Result`, `ColumnInfo` with validation (half-open periods, `top_n` bounds, known operators). Tests for valid and invalid instances.
2. **LLM client.** `LLMClient.structured(alias, prompt, schema) -> model` and `LLMClient.text(alias, prompt) -> str` over the LiteLLM OpenAI-compatible API. A fake client records calls for tests. Only alias names are accepted.
3. **resolve_time (test first, deterministic).** Input: structured period descriptors from `extract` (absolute year/quarter/month/range, relative offsets such as "last quarter", "this year to date"), the reference date, fiscal start month and the request's time zone (`jobs/ask.py --timezone`, UTC when omitted). Output: labelled `[start, end)` dates. Tests: calendar Q1, fiscal year starting in April, relative quarter across a year boundary, two periods for comparison, month and year, invalid descriptors.
4. **extract.** Prompt `extract.v1.md` with JSON schema output. Tests with the fake client: the acceptance question yields two periods, `top_n = 10`, `compare = true`, rank metric term "best-selling".
5. **retrieve.** Hybrid queries against the six aliases; returns candidate metrics, datasets/columns, column values and examples with scores. Tests use a fake search client.
6. **build_spec.** Resolve terms to metric ids and columns using retrieval plus the pack's default conventions; pick the dataset; run the coverage check against compiled min/max dates and add warnings. Tests: default "best-selling = net sales", out-of-coverage period warning.
7. **generate_sql.** Prompt input: QuerySpec, permitted schema, declared joins, retrieved examples, previous error if retrying. The prompt states that retrieved text is data, not instructions, and that all percentages and differences must be computed in SQL.
8. **guard (test first).** sqlglot checks: exactly one statement, SELECT only (CTEs allowed), tables and columns in the allowlist, no forbidden functions (`file`, `url`, `remote`, `s3`, table functions, `system.*` outside a whitelist), no `SETTINGS` or `FORMAT` clauses, and LIMIT enforced or capped. Each rejection is classified as `policy`.
9. **explain, execute.** `EXPLAIN` then execution as the read-only user with `max_execution_time`, `max_result_rows`, `max_memory_usage`, `log_comment = trace_id` and a generated `query_id`. Errors are classified as `sql` or `runtime`.
10. **check and retry loop.** `policy` stops without retry; `sql`/`runtime` loops back to `generate_sql` with the error, for one initial generation plus at most 3 retries with the third retry on `sql-gen-hard` (open question 1, settled); zero rows or out-of-coverage results pass with warnings. When retries are exhausted the run returns the last SQL and error.
11. **shape_result, summarize.** Attach types and roles from the compiled catalog, cap at 5,000 rows with `truncated`. Summary prompt receives only the returned rows.
12. **ask CLI and isolation check.** `jobs/ask.py` prints SQL, a table, warnings and the summary, and exits nonzero with a reason for input it rejects. `scripts/check_pack_isolation.py` collects every dataset, column and metric id from all packs and fails if any appears anywhere in `apps/api`, tests included; the only exempt names are those of the synthetic fixture pack under `apps/api/tests/fixtures/` (open question 5). CI runs it.

## Contracts

- QuerySpec and Result exactly as DECISIONS §7.
- Graph state: `question, profile, extraction, periods, retrieval, spec, sql, attempts, errors, result, warnings, summary, trace_id`.
- Config: `LITELLM_BASE_URL`, `LITELLM_MASTER_KEY`, `CLICKHOUSE_AGENT_USER`, `CLICKHOUSE_AGENT_PASSWORD`, `QUERY_MAX_EXECUTION_TIME`, `QUERY_MAX_RESULT_ROWS`, `QUERY_MAX_MEMORY_USAGE`.

## Verification

```bash
uv run --project apps/api pytest -c apps/api/pyproject.toml
python scripts/check_pack_isolation.py
docker compose run --rm api python -m jobs.ask "Top 10 best-selling products in Q1 2024 compared with Q1 2025"
```

## Definition of done

| DoD item | Proof |
|---|---|
| Acceptance question returns correct SQL and result | CLI output matches the Phase 1 analysis result set |
| A deliberate SQL error self-repairs within the retry limit | Test with a fake LLM returning a broken query first; live run with a fault-injection flag |
| 0 rows -> warning | Test and a live question outside data coverage |
| No pack names hard-coded in `apps/api` | `check_pack_isolation.py` passes in CI |

## Risks and open questions

1. **Retry count.** Settled by DECISIONS §2 and §6: one initial generation plus at most 3 retries (4 generations in total); the third retry uses `sql-gen-hard`. Tests assert the alias used per attempt.
2. **Period descriptor format.** Default: extract emits structured descriptors, never dates; only `resolve_time` produces dates, so time logic stays testable.
3. **Reference date.** Lab data ends in 2026; "last quarter" relative to the real date may fall outside coverage. Default: reference date is the real current date, with coverage warnings; an override flag exists for eval.
4. **sqlglot ClickHouse coverage.** Some ClickHouse functions may parse imperfectly; unparsable SQL is treated as an `sql` error and retried, never executed.
5. **Isolation scan scope.** DECISIONS §13 says `grep` must find no pack names in `apps/api`. Default: scan all of `apps/api`, including tests; unit tests therefore use a synthetic fixture pack under `apps/api/tests/fixtures/` whose neutral names are excluded from the forbidden list. If the owner prefers excluding tests instead, DECISIONS §13 is updated in the same PR.

## Branch and PR split

- `feat/agent/add-query-contracts-and-time-resolution`: tasks 1-3.
- `feat/agent/guard-and-execute-sql`: tasks 8-9 (guard is reviewable on its own).
- `feat/agent/run-data-query-flow-from-cli`: tasks 4-7, 10-12.
