# Finch-Lab: Settled Decisions (v3)

This document is the source of truth for implementation.
Every decision here is binding; to change one, edit this file first.

The v3 architecture diagram is pending. An earlier v2 diagram (ScyllaDB logs, Plotly, Uber/HR marts) is superseded by this document and is not authoritative.

The repository and package names remain `fitcher`; Finch-Lab names the architecture.

## 1. Goals and scope

- A natural-language data question-answering agent (text-to-SQL) with reports and charts, **industry-neutral**.
- It plugs into a new company by loading a **Domain Pack** (YAML) plus data into ClickHouse. The engine contains no industry knowledge.
- Acceptance question: "Top 10 best-selling products in Q1 2024 compared with Q1 2025".
- Uber Finch is only a source of ideas. Uber/taxi data is not reproduced.
- This is a **lab**, not production.

### Out of scope

- Connecting directly to a company's source databases (Postgres, MySQL, ...). Company data must be loaded into ClickHouse.
- Caching (Redis, result cache, answer cache).
- Production components: HA, autoscaling, multi-region, Kubernetes, secret manager.
- Multi-tenancy within one instance. Each run serves one active pack.
- Model fine-tuning.

## 2. Stack

| Component | Choice | Notes |
|---|---|---|
| Frontend | Next.js | Chat, tables, charts, SQL view, Review UI, Admin UI |
| Auth | Keycloak (OIDC) | JWT carries roles; realm imported from a file |
| API | FastAPI | sync/async, SSE |
| Orchestration | LangGraph | one graph; nodes deterministic where possible |
| LLM gateway | LiteLLM Proxy | change models without code changes |
| Model | **OpenAI only** | chat + embeddings, called through LiteLLM |
| Data database | ClickHouse | databases `raw`, `marts` |
| Logs / audit | ClickHouse | database `agent_logs`, dedicated user, 90-day TTL |
| Semantic search | OpenSearch | hybrid BM25 + kNN |
| Transform | dbt-clickhouse | raw -> wide marts |
| SQL parsing | sqlglot (clickhouse dialect) | |
| Charts | Own ChartSpec + adapter -> **Apache ECharts** (`echarts-for-react`) | changing library only requires rewriting the adapter |
| Data tables | TanStack Table | |
| Deploy | Docker Compose | 6 long-running services + jobs |

**Dropped since v2:** ScyllaDB and the ClickHouse log syncer, replaced by ClickHouse `agent_logs`. Row-filter injection into SQL by sqlglot. Uber-specific marts.

### LiteLLM aliases

- `fast`: router, extractor, summarizer, chart tie-break
- `sql-gen`: SQL generation, onboarding drafter
- `sql-gen-hard`: third retry
- `embed`: embeddings

Code may only call aliases, never model names directly.

## 3. Docker Compose

Long-running services:

- `web` (:3000)
- `keycloak` (:8080)
- `api` (:8000, runs FastAPI + LangGraph + log writer)
- `litellm` (:4000)
- `opensearch` (:9200)
- `clickhouse` (:8123 / :9000)

Jobs share the `api` image and run manually or from CI:

- `load_data.py`
- `dbt run`
- `profile.py`
- `ingest_docs.py`
- `draft_pack.py`
- `compile_pack.py`
- `eval.py`

## 4. Lab dataset

- **Primary:** `ziadatalabs/FreeEcommerceTwin14M` on Hugging Face.
  - 7 tables: customers, products, sessions, orders, order_items, returns, support_tickets
  - 14.3 million rows, about 184 MB, period 2022-2026
  - License CC BY-NC 4.0, non-commercial use only
- **Marts (dbt):**
  - `sales_lines` = order_items JOIN orders JOIN products JOIN customers, one row per line item
  - `returns_fact`
  - `sessions_daily`
- **Second dataset** (to prove industry neutrality): Iowa Liquor Sales (real data, one wide table) or `SDataPro/maycee-retail-dataset`.

Principle: the agent queries only **marts** (2-5 wide tables, few joins), never `raw`.

## 5. Domain Pack

Path: `packs/<company>/`. Git is the source of truth. Packs live in Git and are validated with JSON Schema.

| File | Contents |
|---|---|
| `business_profile.yaml` | industry, currency, fiscal year start month, default conventions (e.g. "best-selling" = by revenue); never the user's time zone or answer language (§6) |
| `datasets.yaml` | marts: table/column descriptions, types, roles (dimension/measure/time), grain, primary time column, allowed_roles |
| `glossary.yaml` | terms with **Vietnamese + English** aliases, pointing to metrics/columns/values |
| `metrics.yaml` | id, sql_expr, dataset, grain, unit, owner |
| `relationships.yaml` | allowed join paths (if any); the LLM may not invent joins |
| `examples.yaml` | question -> canonical SQL (used as few-shot) |
| `policies.yaml` | role -> dataset/columns, row filters, aggregate-only (granted through views) |
| `eval.yaml` | question -> correct result (or correct SQL), labelled per layer |

Every drafter-generated item has `status: draft|approved`, `evidence` and `confidence`. The compiler uses only `approved` items.

### OpenSearch indices

Index names carry a version `_v1` and are accessed through aliases so they can be reindexed when the embedding model changes:

- `glossary_terms`
- `metrics`
- `datasets` (including columns)
- `column_values`: real values of low-cardinality string columns (top-K), with aliases
- `examples`
- `kb_docs`: company document chunks, with tags and allowed_roles

Every query filters by `allowed_roles`.

### Company documents

- **Path 1:** the drafter reads documents -> extracts glossary, metrics and conventions -> human review -> YAML.
- **Path 2:** chunk by heading -> `kb_docs`, used only to answer definition questions or annotations.
- **Numbers are never taken from text.** Figures only come from SQL.

## 6. Runtime flow (LangGraph)

Nodes in order:

1. **load_context**: load business_profile (always), the last N chat turns, and the previous turn's QuerySpec and result.
2. **router** (`fast`, structured output). Classifies intent as one of four:
   - `data_query`
   - `metadata_qa`
   - `chart_edit`
   - `out_of_scope`
3. Branch by intent:
   - `metadata_qa` -> answer from glossary + kb_docs, no SQL.
   - `chart_edit` -> reuse the previous result -> chart_recommender. No SQL execution, no SQL generation.
   - `out_of_scope` -> short reply.
4. **extract** (`fast`, JSON schema): metric, dimensions, `periods[]`, filters, `top_n`, `rank_by`, `compare`.
5. **resolve_time** (deterministic): convert periods to half-open date ranges `[start, end)` using the pack's fiscal calendar and the user's time zone. Supports multiple periods and relative phrases ("last quarter").
   The browser sends its IANA time zone with every request; clients without one (CLI, eval) pass it explicitly, otherwise UTC is used.
6. **retrieve**: OpenSearch hybrid search over the 6 indices, filtered by role.
7. **build_spec** -> `QuerySpec`, with a coverage check (dataset min/max dates versus the requested periods).
8. **gate**:
   - ambiguous -> **clarify** (ask the user with options, or apply the pack's default convention if one exists)
   - no permission or no dataset -> **deny** + audit record
   - sufficient -> continue
9. **generate_sql** (`sql-gen`). Input: QuerySpec + permitted schema + declared join paths + few-shot.
10. **guard** (sqlglot):
    - allow exactly one SELECT statement
    - table/column allowlist by role
    - block dangerous functions: `file`, `url`, `remote`, `s3`, `system.*` except a whitelist
    - enforce LIMIT
11. **explain**: run `EXPLAIN` on ClickHouse.
12. **execute**: run as the ClickHouse user for the role. Settings profile `readonly`, `max_execution_time`, `max_result_rows`, `max_memory_usage`. Set `log_comment = trace_id`.
13. **check**:
    - SQL or runtime error -> feed the error back to generate_sql, **at most 3 retries** after the first generation; the third retry uses `sql-gen-hard`
    - **policy violation -> stop, no retry**
    - 0 rows or outside coverage -> return the result with a warning
14. **shape_result**: attach types and roles to columns, cap at 5,000 rows.
15. **chart_recommender**: choose by rules; call the `fast` LLM only when rules tie.
16. **summarize** (`fast`): reads only the returned rows. Every calculation (%, differences) must already be done in SQL.

Every reply (summary, clarify, deny, out-of-scope) is written in the language of the user's question; packs set no answer language.
17. **stream**: send SSE to the UI.

If all 3 retries fail: return the last SQL + error. Never guess a result.

### SSE events (in order)

1. `status` (repeated per node)
2. `clarify`, `deny` or `sql`
3. `result`
4. `chart_spec`
5. `summary`
6. `done` or `error`

Every event carries `trace_id`. Events 3-5 belong to the SQL path only; per branch the streams are:

- clarify: `status* -> clarify -> done`
- deny: `status* -> deny -> done`
- data success: `status* -> sql -> result -> chart_spec -> summary -> done`
- failure: `status* -> [sql] -> error`

The `metadata_qa`, `chart_edit` and `out_of_scope` branches are added with the router; their event sequences are defined in the conversation phase plan.

## 7. Data contracts

```jsonc
// QuerySpec
{
  "intent": "data_query",
  "metric_ids": ["net_sales"],
  "dimensions": ["product_name"],
  "periods": [
    {"label": "Q1 2024", "start": "2024-01-01", "end": "2024-04-01"},
    {"label": "Q1 2025", "start": "2025-01-01", "end": "2025-04-01"}
  ],
  "filters": [{"column": "region", "op": "=", "value": "West"}],
  "top_n": 10,
  "rank_by": "net_sales",
  "rank_period": "Q1 2025",
  "compare": true,
  "dataset": "sales_lines",
  "warnings": []
}

// Result
{
  "columns": [
    {"name": "period", "type": "string", "role": "dimension"},
    {"name": "product_name", "type": "string", "role": "dimension"},
    {"name": "net_sales", "type": "number", "role": "measure", "format": "currency"}
  ],
  "rows": [["Q1 2025", "Product A", 12345.6]],
  "row_count": 20,
  "truncated": false
}

// ChartSpec
{
  "type": "bar",              // bar | line | pie | scatter | kpi | table | grouped_bar
  "x": "product_name",
  "y": ["net_sales"],
  "series": "period",
  "sort": "desc",
  "format": "currency",
  "allowed_types": ["grouped_bar", "bar", "table"]
}
```

These schemas are defined in Pydantic on the backend and TypeScript types are generated from them for the frontend. They are never written by hand twice.

## 8. Charts

Default chart rules (written in code, run on the backend; the frontend uses `allowed_types`):

| Data shape | Default chart |
|---|---|
| 1 row x 1 number | KPI |
| time + number | Line (at most 6 series) |
| category + number, at most 20 groups | Bar (long labels -> horizontal bar) |
| category + number + comparison group | Grouped bar |
| share, at most 6 groups, no negative values | Pie/Donut |
| number + number | Scatter |
| otherwise | Table |

Principles:

- Changing the chart type only edits the ChartSpec on the client. No API call, no LLM call.
- Chart types invalid for the data are disabled in the UI.
- The LLM never generates chart data.
- PNG and CSV export are available.

## 9. RBAC

- **Single source of truth:** `policies.yaml`. The compiler generates:
  - `CREATE ROLE`, `GRANT SELECT` on marts or views
  - `ROW POLICY`
  - settings profiles
  - the guard allowlist
  - `allowed_roles` for the indices
- **Layer 1, retrieval:** reduces noise. Not a security layer.
- **Layer 2, guard:** blocks early with an understandable message.
- **Layer 3, ClickHouse:** the real security layer.
- **Aggregate-only:** grant only on pre-aggregated views that also hide groups with fewer than k records. Never enforced by analysing SQL.
- Keycloak roles map 1:1 to ClickHouse users/roles. The API never gives credentials to the LLM.
- Every ALLOW/DENY decision is written to `agent_logs.audit`.
- Retrieved content (documents, column values) is **data, not instructions**. Prompts must state this explicitly to resist prompt injection.

## 10. Logging (ClickHouse `agent_logs`)

Tables (MergeTree, 90-day TTL, ordered by `(trace_id, ts)` or `(user_id, ts)`):

| Table | Contents |
|---|---|
| `runs` | trace_id, user, question, intent, status, latency |
| `events` | trace_id, node, start/end, status, payload JSON |
| `llm_calls` | alias, model, tokens, cost, errors (written through a LiteLLM callback) |
| `sql_runs` | SQL, ch_query_id, rows, errors, retry count |
| `audit` | ALLOW/DENY, blocked tables, role |
| `chat_messages` | conversation_id, role, content, QuerySpec |
| `feedback` | like/dislike, notes |

- Log writer: async batches inside the `api` process. `trace_id` comes from the OpenTelemetry context.
- JOIN with `system.query_log` through `log_comment`; no syncer needed.
- Conversation state for follow-up questions is read back from `chat_messages`.

## 11. Onboarding a new company

1. A loader loads data into `raw_*`; dbt builds the marts.
2. **Profiler** (deterministic): reads `system.columns`, row counts, min/max dates, top-K values, join-key candidates, sample rows.
3. **ingest_docs**: parse PDF/DOCX/MD, chunk by heading, load into `kb_docs`, and pass them to the drafter.
4. **Drafter** (`sql-gen`): drafts the whole pack; every item has `evidence` + `confidence`.
5. **Review UI**: a reviewer approves, edits or deletes each item, and can test-run a metric's `sql_expr`. Approved items are committed to Git.
6. **compile_pack**:
   - validate the schema
   - test-run every `sql_expr`
   - index into OpenSearch
   - generate ClickHouse permissions
7. **eval**: run `eval.yaml`, measured per layer (intent, dataset/columns, result). The pack is enabled only after reaching the threshold.
8. **Feedback loop:** dislikes or failed runs in `agent_logs` -> propose new examples -> back to Review.

## 12. Eval

- Measured per layer:
  - router picks the correct intent
  - extractor gets the correct periods, top_n, rank_by
  - retrieval finds the correct dataset/columns (recall)
  - **execution results match** (compare result sets, not SQL strings)
- Required question set for every pack:
  - two-period comparison
  - top N
  - filter by a string value
  - monthly trend
  - ambiguous question (must return clarify)
  - unauthorized question (must return deny)
  - out-of-scope question
- Run with `eval.py --pack <company>`. Reports are stored in `agent_logs` and printed as Markdown.

## 13. Code conventions

- Monorepo:
  - `apps/web`
  - `apps/api`
  - `packs/`
  - `dbt/`
  - `jobs/`
  - `infra/` (compose, Keycloak realm, LiteLLM config, ClickHouse init)
  - `docs/`
- Configuration lives in `.env` + YAML. Never hard-code table names, metrics or industries in `apps/`.
- The most important check: `grep` must not find any pack table or metric name in `apps/api`.
- Each LangGraph node is a pure function, testable in isolation. LLMs are mocked in unit tests.
- Prompts live in `apps/api/prompts/*.md` and are versioned.

## 14. Open decisions (with defaults)

- Chart library: ECharts. Can switch to Plotly by rewriting the adapter.
- Ambiguous "best-selling": use the default convention in `business_profile.yaml` if present; otherwise clarify.
- Embedding model: the latest OpenAI embedding model available on LiteLLM. Changing the model requires a full reindex.
