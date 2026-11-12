# fitcher: Settled Decisions (v4)

This document is the source of truth for implementation.
Every decision here is binding; to change one, edit this file first.

v4 turns fitcher from a six-service lab into a self-hosted product that starts with one Docker command.
The reasoning, measurements and sources behind v4 are in [self-hosted-product-assessment.md](self-hosted-product-assessment.md).
The architecture diagram in [finch-architecture.excalidraw](finch-architecture.excalidraw) and [architecture/](architecture/) still draws v3 and is redrawn in Phase 21; where it and this document disagree, this document wins.
This document states the target. §16 lists each decision that differs from the code built in Phases 0 to 12 and the phase that implements it; until that phase is merged, the code keeps the earlier behaviour and nobody removes it ahead of its phase.

## 1. Goals and scope

- A natural-language data question-answering agent (text-to-SQL) with reports and charts, **industry-neutral**.
- It plugs into a new company by loading a **Domain Pack** (YAML) and connecting the company's data through ClickHouse (§4): a source is read live through a ClickHouse database or table engine or copied into ClickHouse on a schedule. The engine contains no industry knowledge and queries only ClickHouse.
- Acceptance question: "Top 10 best-selling products in Q1 2024 compared with Q1 2025".
- Uber Finch is only a source of ideas. Uber/taxi data is not reproduced.
- It is an **open-source, self-hosted product** for developers who run it on their own machine or server: one image, one container, one data volume and one published port (§3). The reference machine is a laptop with 8 GB of memory.
- A first-run setup (§15) asks who uses the instance (one person or a team), which models to use, which data to connect and whether to add company documents. Nothing requires editing a file.

### Out of scope

- Querying a source database from the engine in its own dialect or over its own driver. Every source is reached through ClickHouse (§4), so the agent writes one SQL dialect and RBAC stays in ClickHouse (§9).
- Writing to a source database.
- Caching (Redis, result cache, answer cache).
- Clustered operation: HA, autoscaling, multi-region, Kubernetes, an external secret manager.
- A native desktop application. Docker is the only supported way to run fitcher.
- Connecting to a source through an SSH tunnel, change data capture and streaming ingestion.
- Telemetry: the application sends nothing about its use to anyone.
- Multi-tenancy within one instance. Each run serves one active pack.
- Model fine-tuning.

## 2. Stack

| Component | Choice | Notes |
|---|---|---|
| Frontend | Next.js | Chat app and workspace console (§15): chat, tables, charts, SQL view, Review, Documents and Admin pages; English/Vietnamese interface, light and dark themes |
| Auth | Built into `api` | Individual mode has no sign-in; team mode has local accounts and server-side sessions, with any OIDC provider as an optional sign-in (§9) |
| App state | SQLite file in the data volume | settings, encrypted secrets, accounts, sessions, sources and the setup state; ClickHouse keeps data and logs |
| API | FastAPI | sync/async, SSE |
| Orchestration | LangGraph | one graph; nodes deterministic where possible |
| LLM gateway | LiteLLM Python SDK inside `api` | one client for every provider; no proxy service |
| Model | OpenAI, Anthropic, Gemini, Ollama and any OpenAI-compatible endpoint (LM Studio, OpenRouter and similar) | providers and keys are entered in the application (§15); chat tiers are called through the gateway |
| Embeddings | Local multilingual model through fastembed by default; a provider's embedding model as an option | no key is needed to index a pack; changing the model needs a full reindex (§14) |
| Input screening | EN/VI rules always; Llama Prompt Guard 2 86M (local ONNX) as an option | a security classifier, not an answering model (§9) |
| Data database | ClickHouse | databases `raw`, `marts`; sources attached through engines or copied (§4) |
| Logs / audit | ClickHouse | database `agent_logs`, dedicated user, 90-day TTL |
| Semantic search | ClickHouse | hybrid dense + BM25 sparse scoring fused with RRF; Qdrant is used until Phase 20 proves no loss of recall (§16) |
| Transform | dbt-clickhouse | raw -> wide marts |
| SQL parsing | sqlglot (clickhouse dialect) | |
| Charts | Own ChartSpec + adapter -> **Apache ECharts** (`echarts-for-react`) | changing library only requires rewriting the adapter |
| Data tables | TanStack Table | |
| Deploy | One Docker image | one container supervised by s6-overlay; Compose is the development environment (§3) |

**Dropped since v2:** ScyllaDB and the ClickHouse log syncer, replaced by ClickHouse `agent_logs`. Row-filter injection into SQL by sqlglot. Uber-specific marts.

**Dropped in v4:** Keycloak, the LiteLLM Proxy service and the Qdrant service.

### Model tiers

The engine calls a task tier; each tier maps to one model of a configured provider:

- `fast`: router, extractor, summarizer, chart tie-break
- `sql-small`: SQL generation for a query spec the complexity rule scores as simple (§6)
- `sql-gen`: SQL generation otherwise, the first retry after a `sql-small` failure, onboarding drafter
- `sql-gen-hard`: third retry
- `embed`: embeddings

Code may only call tiers, never model names directly. Providers, their keys or base URLs and the tier mapping are stored in the app state and edited in the setup and on the Models page (§15). Adding a provider proposes a default model for every chat tier. A model that has no passing pack eval for its tier is allowed and shown as not evaluated; the eval informs the choice and no longer gates it. Changing `embed` is a separate, confirmed action because it reindexes the pack (§14).

## 3. Deployment

fitcher ships as one image. The documented start is one command that publishes one port on loopback and mounts one volume:

```bash
docker run -d --name fitcher -p 127.0.0.1:3000:3000 -v fitcher-data:/data ghcr.io/nguyenminh1301/fitcher
```

- **Processes.** s6-overlay supervises `web` (the only published port), `api` and an embedded ClickHouse server. They talk over loopback inside the container. A process that cannot be restarted stops the container, and the image healthcheck covers all three.
- **Embedded or external.** ClickHouse is embedded unless `CLICKHOUSE_URL` points to an external server; a sample Compose file shows that layout. No other service is required in any layout.
- **Data.** Everything that must survive lives under `/data`: the ClickHouse data, the app state file, packs, documents, downloaded models and the generated secret key. Backing up the instance is copying that volume.
- **Secrets.** The key that encrypts stored secrets is generated on first start in `/data`, or supplied as `FITCHER_SECRET_KEY`. ClickHouse users get generated passwords; the embedded server listens on loopback only.
- **Memory.** The embedded ClickHouse runs a low-memory profile sized from the container's memory limit: a server memory cap, a small mark cache, no metric or trace system logs, and aggregation and sorting that spill to disk.
- **Upgrades.** Every start applies the pending numbered schema changes to the app state and to ClickHouse, each recorded in a version table. A newer image therefore upgrades an older volume in place; a volume written by a newer image refuses to start on an older one.
- **Local models.** A model server on the host is reached as `host.docker.internal`; on Linux the command adds `--add-host=host.docker.internal:host-gateway`.
- **Jobs.** The job modules (`sync_sources`, `profile`, `draft_pack`, `compile_pack`, `eval`, `ingest_docs` and the others) are in the image and run with `docker exec`; the application starts the same code from the console.
- **Development.** `compose.yaml` builds `api`, `web` and ClickHouse as separate services and keeps the `sources` fixtures and the `local-models` profile. dbt and the lab datasets are development tools and are not in the released image.

## 4. Development datasets and data sources

The two datasets below exist to develop and evaluate the engine. Their packs, source manifests and dbt models stay in the repository and are never part of the released image; the public demo is the web app on hand-written sample data (§15).

- **Primary:** `ziadatalabs/FreeEcommerceTwin14M` on Hugging Face.
  - 7 tables: customers, products, sessions, orders, order_items, returns, support_tickets
  - 14.3 million rows, about 184 MB, period 2022-2026
  - License CC BY-NC 4.0, non-commercial use only
- **Marts (dbt):**
  - `sales_lines` = order_items JOIN orders JOIN products JOIN customers, one row per line item
  - `returns_fact`
  - `sessions_daily`
- **Second dataset** (to prove industry neutrality): Iowa Liquor Sales 2025, chosen over `SDataPro/maycee-retail-dataset` because it is real data from a clearly different industry (state-regulated spirits wholesale) under a clear licence.
  - Iowa Data Hub dataset 1262: every Class E liquor licensee purchase in Iowa from 2025-01-01 to 2025-12-31, one wide table of invoice lines (store, county, category, vendor, item, bottle size, state cost and retail, bottles, dollars, volume)
  - License CC BY 4.0, published by the Iowa Department of Revenue, Alcohol Operations Bureau; the download stays in the Git-ignored `data/` directory
  - Served from the fixture PostgreSQL (`infra/sources/iowa_liquor`) and copied into ClickHouse through its source manifest like a company's own database; pack `iowa_liquor`

Principle: the agent queries only **marts**, never `raw` or `src_*`. A mart is either a wide table built by a transform (the development datasets use dbt) or, for a source connected in the application, a view over one selected source table (§11).

### Data sources

A company's data is always reached through ClickHouse. A source is created on the Sources page (§15) and stored in the app state; a source manifest (`jobs/sources/<pack>.yaml`) declares the same thing as a file for development and scripted setups:

| Kind | Live mode | Copy mode |
|---|---|---|
| PostgreSQL | `PostgreSQL` database engine in database `src_<source>` | scheduled `INSERT INTO raw.* SELECT` from the source |
| MySQL / MariaDB | `MySQL` database engine in database `src_<source>` | same |
| MongoDB | `MongoDB` table engine with declared columns (flat collections only) | same |
| SQL Server | `ODBC` table engine through `clickhouse-odbc-bridge` and FreeTDS | same |
| Uploaded CSV / Excel / Parquet file | none | load into `raw` |
| S3 files (manifest only) | `S3` table engine | load into `raw` |

- The mode is chosen per table. **Live** is the default for a small table: nothing is stored twice and answers are always fresh. **Copy** is proposed for a table above the size threshold (§14), because ClickHouse pushes only simple `WHERE` filters to a source and runs joins, aggregation and sorting itself after reading the rows; a copied table is queried at ClickHouse speed and is as fresh as its last sync.
- A copy is refreshed on a schedule kept in the app state and run inside `api`. A table with an increasing key or modification time is copied incrementally from the last value seen; any other table is reloaded and swapped atomically.
- MongoDB and S3 sources are declared in a manifest only; the Sources page does not offer them.
- The agent still queries only marts, writes ClickHouse SQL and runs under the ClickHouse RBAC of §9; `src_*` databases are granted to no agent role.
- Each source has a read-only user on the source system. Its credentials are written once into a ClickHouse named collection created with SQL and stored encrypted by ClickHouse; the app state keeps only the source's name, kind, host and tables. Credentials are never read back, never shown again in the interface and never reach a prompt or the LLM.
- Generating MongoDB queries (or any non-SQL query language) is out of scope: a document collection that is not flat is copied and flattened by dbt.

## 5. Domain Pack

Path: `<packs dir>/<company>/`, in the data volume of a running instance. Packs are YAML files validated with JSON Schema; an instance exports and imports a pack as an archive, and keeping it in Git is the owner's choice. The packs under `packs/` in the repository are development fixtures.

| File | Contents |
|---|---|
| `business_profile.yaml` | industry, currency, fiscal year start month, default conventions (e.g. "best-selling" = by revenue); never the user's time zone or answer language (§6) |
| `datasets.yaml` | marts: table/column descriptions, types, roles (dimension/measure/time), grain, primary time column, allowed_roles |
| `glossary.yaml` | terms with **Vietnamese + English** aliases, pointing to metrics/columns/values |
| `metrics.yaml` | id, sql_expr, dataset, grain, unit, owner |
| `relationships.yaml` | allowed join paths (if any); the LLM may not invent joins |
| `examples.yaml` | question -> canonical SQL (used as few-shot), optionally with a reviewed spec (§6 step 7) |
| `policies.yaml` | role -> dataset/columns, row filters, aggregate-only (granted through views) |
| `eval.yaml` | question -> correct result (or correct SQL), labelled per layer |

Every drafter-generated item has `status: draft|approved`, `evidence` and `confidence`. The compiler uses only `approved` items. An instant pack (§11) approves its generated items automatically and marks them `reviewed: false`, which the interface shows as unreviewed until a person confirms them.

### Search collections

Each index below holds a dense vector (`embed`) and a BM25 sparse vector per item. Every pack generation writes a new versioned set and the live one is switched atomically, so a pack can be reindexed when the embedding model changes:

- `glossary_terms`
- `metrics`
- `datasets` (including columns)
- `column_values`: real values of low-cardinality string columns (top-K), with aliases
- `examples`
- `kb_docs`: company document chunks, with tags and allowed_roles; absent when documents are turned off (§15)

Every query filters by `allowed_roles` and fuses the dense and sparse results with RRF.

### Company documents

- **Path 1:** the drafter reads documents -> extracts glossary, metrics and conventions -> human review -> YAML.
- **Path 2:** chunk by heading -> `kb_docs`, used only to answer definition questions or annotations.
- **Numbers are never taken from text.** Figures only come from SQL.

Documents are runtime content managed in the application, not files in Git; the pack YAML stays the reviewed source for datasets, metrics and policies.

- **Formats:** PDF (text layer only, no OCR), DOCX, Markdown, plain text and XLSX (cell values with the sheet's header row; formulas are not evaluated and macro-enabled workbooks are rejected). A spreadsheet of business data is data, not a document: it is loaded into ClickHouse (§1).
- **Upload and delete at any time:** a `pack_reviewer` uploads, lists and deletes documents on the Documents page of the web app, choosing each document's `allowed_roles` from the pack's roles. `ingest_docs.py` loads a folder through the same code path for bulk onboarding.
- **Storage:** original files live in the `api` service's documents volume. The registry table `data_meta.documents` records id, pack, file name, type, size, SHA-256, uploader, `allowed_roles`, status (`processing`, `indexed`, `failed`) with the error, and upload and delete times; a dedicated ClickHouse user writes only that table. A file whose SHA-256 is already registered for the pack is rejected as a duplicate.
- **Upload:** check the type from the file content and a size cap, store the file, parse, chunk, screen each chunk (§9), embed through `embed` and index the chunks into the pack's live `kb_docs` alias. A failure marks the document `failed` and leaves no chunks.
- **Delete:** remove the document's chunks from `kb_docs`, delete the stored file and mark the registry row deleted. Pack items whose evidence cites the document are flagged in the Review UI; approved YAML is never changed automatically.
- **Drafting from a document** is an explicit, billable reviewer action; its items go through review like every draft.
- **Compile:** each pack generation rebuilds `kb_docs` from the registry's indexed documents, copying the chunks of the live generation when the embedding model is unchanged and re-embedding the stored files otherwise. Uploads and deletes are rejected while that pack compiles, so a compile never drops or restores a document.

## 6. Runtime flow (LangGraph)

Nodes in order:

0. **screen** (deterministic rules, plus the local classifier when it is enabled, §9): screens the new question before any LLM call. `block` ends the run with a `blocked` reply; `flag` continues and is logged.
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
6. **retrieve**: hybrid search over the search collections (§5). Candidates for the question's own terms (metrics, dimensions, filter values) are searched across all of the pack's roles, so a term resolves to what it means and the gate can deny it rather than replace it with the nearest item the role may read; the context given to SQL generation (examples, dataset hits) is filtered by the asking role.
7. **build_spec** -> `QuerySpec`, with a coverage check (dataset min/max dates versus the requested periods).
   When an approved example readable by the asking role asks the same question (compared case-, diacritic- and punctuation-insensitively) and carries a reviewed spec, that spec's metrics, dataset, dimensions, filters, top N and ranking replace the term resolution; periods and time grain still come from the question, and the gate checks the result as usual. A reviewed spec names only pack items and pack values, never a value taken from a user's run.
8. **gate**:
   - ambiguous -> **clarify** (ask the user with options, or apply the pack's default convention if one exists)
   - no permission or no dataset -> **deny** + audit record
   - sufficient -> continue
9. **generate_sql**: tier `sql-small` when the deterministic complexity rule scores the QuerySpec as simple (one metric, at most one dimension, one period, no comparison, no top N, one dataset), otherwise `sql-gen`. Input: QuerySpec + permitted schema + declared join paths + few-shot.
10. **guard** (sqlglot):
    - allow exactly one SELECT statement
    - table/column allowlist by role
    - block dangerous functions: `file`, `url`, `remote`, `s3`, `system.*` except a whitelist
    - enforce LIMIT
11. **explain**: run `EXPLAIN` on ClickHouse.
12. **execute**: run as the ClickHouse user for the role. Settings profile `readonly`, `max_execution_time`, `max_result_rows`, `max_memory_usage`. Set `log_comment = trace_id`.
13. **check**:
    - SQL or runtime error -> feed the error back to generate_sql, **at most 3 retries** after the first generation; a retry after a `sql-small` attempt moves to `sql-gen`, and the third retry uses `sql-gen-hard`
    - **policy violation -> stop, no retry**
    - 0 rows or outside coverage -> return the result with a warning
14. **shape_result**: attach types and roles to columns, cap at 5,000 rows.
15. **chart_recommender**: choose by rules; call the `fast` LLM only when rules tie.
16. **summarize** (`fast`): reads only the returned rows. Every calculation (%, differences) must already be done in SQL.

Every reply (summary, blocked, clarify, deny, out-of-scope) is written in the language of the user's question; packs set no answer language.
17. **stream**: send SSE to the UI.

If all 3 retries fail: return the last SQL + error. Never guess a result.

### SSE events (in order)

1. `status` (repeated per node)
2. `blocked`, `clarify`, `deny` or `sql`
3. `result`
4. `chart_spec`
5. `summary`
6. `done` or `error`

Every event carries `trace_id`. Events 3-5 belong to the SQL path only; per branch the streams are:

- blocked: `status* -> blocked -> done`
- clarify: `status* -> clarify -> done`
- deny: `status* -> deny -> done`
- data success: `status* -> sql -> result -> chart_spec -> summary -> done`
- failure: `status* -> [sql] -> error`
- out_of_scope: `status* -> summary -> done`
- metadata_qa: `status* -> summary -> done`
- chart_edit: `status* -> result -> chart_spec -> done`, re-sending the stored result so the client always has the rows it draws

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
  "orientation": "vertical",  // optional, bar only: vertical | horizontal (long labels)
  "allowed_types": ["grouped_bar", "bar", "table"]
}
```

These schemas are defined in Pydantic on the backend and TypeScript types are generated from them for the frontend. They are never written by hand twice. Until a contract has its Pydantic model, the web app's sample-data mode (§15) keeps its type in one provisional file, which the phase that adds the model deletes.

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
- The interface labels the `pie` type as a donut; the contract keeps `pie`.

## 9. RBAC

- **Single source of truth:** `policies.yaml`. The compiler generates:
  - `CREATE ROLE`, `GRANT SELECT` on marts or views
  - `ROW POLICY`
  - settings profiles
  - the guard allowlist
  - `allowed_roles` for the indices
- **Layer 1, retrieval:** reduces noise in the context given to SQL generation. Not a security layer: term resolution may see items the role cannot read, and the gate denies them.
- **Layer 2, guard:** blocks early with an understandable message.
- **Layer 3, ClickHouse:** the real security layer.
- **Aggregate-only:** grant only on pre-aggregated views that also hide groups with fewer than k records. Never enforced by analysing SQL.
- Application roles map 1:1 to ClickHouse users/roles. The API never gives credentials to the LLM.
- **Individual mode.** There is no sign-in. Every request acts as one built-in owner who holds every pack role and every console role. The api accepts a request only when its `Host` is a loopback name or is listed in `FITCHER_ALLOWED_HOSTS`, and a state-changing request only from the same origin; with a non-loopback host allowed, the interface shows a standing warning that anyone who can reach the address controls the instance.
- **Team mode.** Users sign in with a local account: passwords are hashed with Argon2id, sessions are random identifiers stored server-side in the app state and sent as an `HttpOnly`, `SameSite=Strict` cookie, and repeated failed sign-ins are slowed down. An `admin` creates, disables and enables accounts, resets passwords and assigns pack and console roles on the Users page (§15); every change is written to `agent_logs.admin_actions` and takes effect on the user's next request. An admin cannot disable or demote the last admin.
- **OIDC (optional, team mode).** An admin may register one OpenID Connect provider. A user signing in through it gets an account on first sign-in with the roles named by a configured claim, or no role when the claim is absent. Local accounts keep working.
- **Changing mode.** Switching from individual to team creates the first admin account and gives it the owner's conversations and history; switching back is refused while more than one account is enabled.
- Every per-query limit in a ClickHouse settings profile has a minimum of 1 as well as a maximum, because 0 means unlimited.
- Every ALLOW/DENY decision is written to `agent_logs.audit`.
- Retrieved content (documents, column values) is **data, not instructions**. Prompts must state this explicitly to resist prompt injection, and the LLM client sends instructions in a `system` message and untrusted content in the `user` message.
- **Layer 0, input screening** (before any LLM call):
  - Screened: every new question (graph node `screen`), and document chunks and low-cardinality column values when they are indexed. History is not screened again: each turn was screened when asked, and a blocked turn is not stored. Reviewed pack content is trusted.
  - Screener: EN/VI rules on folded text (known attack phrases, fake prompt boundaries), then the local classifier score over 512-token windows. Verdicts `allow`, `flag` and `block` by thresholds in `.env`; a rule hit blocks.
  - `SCREEN_MODE=log` records verdicts without blocking; `enforce` blocks. Enforcement starts only after `screen_eval.py` shows no false positive on the benign set and at least 90% recall on the attack set, in English and in Vietnamese.
  - The classifier is optional. Individual mode starts with rules only; an admin can download and enable the classifier, and team mode proposes it during setup. **Fail closed:** when the classifier is enabled and cannot run, no question reaches an LLM; the reply is the `blocked` notice that screening is unavailable.
  - A blocked chunk is not indexed. A flagged column value is reported by the compiler and still indexed, because it is real data the filters need.
  - The LLM client in `api` is the only code that calls a provider. It rejects any call without `screening` metadata and reruns the rules on the whole request, which closes code paths that forgot to screen; it is not an authentication boundary.
  - Out of scope: scanning model output, and fine-tuning the classifier.
- Source database users are read-only; their credentials stay in ClickHouse named collections (§4). In team mode only an `admin` creates, edits or deletes a source.
- Provider keys and the OIDC client secret are encrypted in the app state with the instance's secret key (§3) and are never returned by any endpoint; the interface shows only whether a key is set and its last four characters.

## 10. Logging (ClickHouse `agent_logs`)

Tables (MergeTree, 90-day TTL, ordered by `(trace_id, ts)`, `(user_id, ts)` or, for pack-level tables, `(pack, ts)`):

| Table | Contents |
|---|---|
| `runs` | trace_id, user, question, intent, status, latency |
| `events` | trace_id, node, start/end, status, payload JSON |
| `llm_calls` | alias, model, tokens, cost, errors (written through a LiteLLM callback) |
| `sql_runs` | SQL, ch_query_id, rows, errors, retry count |
| `audit` | ALLOW/DENY, blocked tables, role |
| `chat_messages` | conversation_id, turn, revision, role, content, QuerySpec, shaped Result (at most 5,000 rows), the answer's other stream events so a conversation shows again as it was answered |
| `conversations` | conversation_id, user, title, pinned, group, deleted flag, update time (§15) |
| `conversation_groups` | group id, user, name, deleted flag, update time (§15) |
| `feedback` | like/dislike, notes |
| `eval_reports` | pack, execution rate, threshold result, full JSON report from `eval.py` (§12) |
| `example_proposals` | pack, question, SQL and source trace proposed from dislikes or failed runs (§11 step 8) |
| `admin_actions` | acting admin, action, target user, old and new value (§9) |
| `input_screening` | trace_id, user, source (question, document, column value), verdict, mode, score, rule hits, classifier version (§9) |

- Log writer: async batches inside the `api` process. `trace_id` comes from the OpenTelemetry context.
- JOIN with `system.query_log` through `log_comment`; no syncer needed.
- Conversation state for follow-up questions is read back from `chat_messages`: for each turn the latest revision, without the turns that an edit or retry of an earlier turn replaced (§15).
- `conversations` and `conversation_groups` are `ReplacingMergeTree` tables keyed by user and id with the update time as version, so a rename, pin, move or delete is a new row; they expire 90 days after their last update, like the messages.

## 11. Onboarding a new company

0. **Instant pack** (the default path in the application): after a source is connected and its tables chosen, the application exposes each chosen table as a mart, reads the source's foreign keys and the profiler's join-key candidates into `relationships.yaml`, runs the profiler and the drafter, approves the generated items as unreviewed (§5) and compiles the pack. The first question can be asked without any manual step; the drafter is a billable call that the setup labels and confirms. The steps below are the same pipeline run by hand, and remain how a pack is refined.
1. **Connect** the company's sources (§4): each one live through a ClickHouse engine or copied into `raw`; marts are views over the chosen tables, or tables built by a transform.
2. **Profiler** (deterministic): reads `system.columns`, row counts, min/max dates, top-K values, join-key candidates, sample rows.
3. **Documents**: a reviewer uploads PDF/DOCX/MD/TXT/XLSX files on the Documents page, or `ingest_docs.py` loads a folder; they are parsed, chunked, screened (§9) and indexed into `kb_docs`, can be deleted at any time (§5) and can be passed to the drafter.
4. **Drafter** (`sql-gen`): drafts the whole pack; every item has `evidence` + `confidence`.
5. **Review UI**: a reviewer approves, edits or deletes each item, and can test-run a metric's `sql_expr`. Approved items are committed to Git.
6. **compile_pack**:
   - validate the schema
   - test-run every `sql_expr`
   - build the search collections (§5)
   - generate ClickHouse permissions
7. **eval**: run `eval.yaml`, measured per layer (intent, dataset/columns, result). The result is shown on the Evaluation page and against each model on the Models page; it does not block using the pack.
8. **Feedback loop:** dislikes or failed runs in `agent_logs` -> propose new examples (in bulk with `propose_examples.py`, or for one run from the Feedback page) -> back to Review.

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
- Run with `eval.py --pack <company>`, or by an `admin` from the Evaluation page (§15). Reports are stored in `agent_logs` and printed as Markdown.

## 13. Code conventions

- Monorepo:
  - `apps/web`
  - `apps/api`
  - `packs/`
  - `dbt/`
  - `jobs/`
  - `infra/` (image and process supervision, ClickHouse configuration and schema changes, development fixtures)
  - `docs/`
- Deployment configuration is a small set of environment variables (§3); everything a user chooses lives in the app state and is edited in the application. Never hard-code table names, metrics or industries in `apps/`.
- The most important check: `grep` must not find any pack table or metric name in `apps/api`.
- Each LangGraph node is a pure function, testable in isolation. LLMs are mocked in unit tests.
- Prompts live in `apps/api/prompts/*.md` and are versioned.

## 14. Open decisions (with defaults)

- Chart library: ECharts. Can switch to Plotly by rewriting the adapter.
- Ambiguous "best-selling": use the default convention in `business_profile.yaml` if present; otherwise clarify.
- Embedding model: `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` (384 dimensions) through fastembed, downloaded into the data volume on first use. It is confirmed only if retrieval recall on the English and Vietnamese retrieval sets does not fall below the current provider model; otherwise the next multilingual fastembed model is measured. Changing the model requires a full reindex.
- Pack eval threshold (§11): execution match >= 80% of the active eval cases; below it `eval.py` exits 1. The threshold is a report, not a gate on using a pack or a model.
- Live or copy (§4): a table is proposed as live below 1 million rows or 1 GB at the source, whichever the source reports, and as copy above; the user can override either way.
- Search engine (§2): search moves into ClickHouse only if `retrieval_eval.py` shows no loss of recall against Qdrant on both development packs; otherwise Qdrant stays as a supervised process inside the container.
- Conversation retention: conversations and their messages are kept until deleted; run logs keep the 90-day TTL (§10). Settled when Phase 21 separates the two.
- Screening thresholds (§9): `flag` from 0.5 and `block` from 0.9, tuned from the `screen_eval.py` report before enforcement.
- SQL complexity rule (§6): simple means one metric, at most one dimension, one period, no comparison, no top N and one dataset; it can be widened only if the pack eval does not regress.
- A provider passes for a tier when the pack eval run with that tier's alias on the provider meets the threshold and does not regress against the baseline.

## 15. Web application

The interface follows the Fitcher web app design, summarized in [design/web-app.md](design/web-app.md); its component names are the names used in `apps/web`.

- **Setup.** A new instance opens on a setup of four steps, each of which can be changed later in the console: who uses the instance (individual or team, creating the first admin for a team), models (pick a provider, enter a key or a base URL, test it, accept the proposed tier mapping), data (connect a source and choose tables, or skip) and documents (on by default, or off). The setup can be left after the models step; the chat then explains what is still missing.
- **Sources page** (`admin`, or the owner in individual mode). Lists the sources with their kind, host, tables, mode and last sync. Adding a source asks for the kind and its connection fields (host, port, database, schema, user, password, TLS mode and certificate; a file upload for the file kind), tests the connection, lists the tables with their size and proposed mode, and saves. A saved password is never shown again.
- **Two surfaces, one sign-in.** The Chat app is for every role. The workspace console is for console roles: `pack_reviewer` sees Review, Documents, Datasets, Feedback and Evaluation; `admin` sees Runs and trace, Audit, Costs, Evaluation, Models and Users. Navigation lists only the sections the user's roles allow, and the api enforces the same rule on every endpoint. A console role reaches the console from the account menu.
- **Conversations.** A user can start, list, search, pin, rename and delete their own conversations and sort them into personal groups. The sidebar shows Pinned, Groups and Recent (today, past week, past month). A group is a folder only: conversations never share context, and there is no sharing or collaboration. A conversation's title is its first question cut to 80 characters; no LLM call names it. Search matches titles and the user's own questions, inside the user's conversations only. Delete only hides the conversation from its owner, at once: nothing is removed, and an `admin` can still read every conversation, deleted or not, with its messages and runs in the console's Runs and trace section. The rows expire with the 90-day log TTL, after which history is gone for everyone.
- **Messages.** Under an answer: copy, like, dislike with an optional note, and retry. Under the user's own message: copy and edit. Edit and retry write a new revision of that turn and answer it again; the turns after it in the older revision leave the conversation and its context.
- **Language.** The English/Vietnamese switch translates the interface only: navigation, labels, step names, notices the app raises, chart axes and number and date formats. User messages, answers and pack content keep the language they were written in (§6). The choice is kept per browser.
- **Theme.** Light and dark, following the system setting unless the user picks one; the choice is kept per browser.
- **Visual system.** Primer-based colour, type and spacing tokens with the fitcher neutrals from `docs/brand`, the Inter font with its Vietnamese subset, Lucide icons; WCAG 2.2 AA in both themes.
- **Datasets page.** A read-only view of the compiled pack's datasets: columns, types, roles and which pack roles may read each dataset.
- **Feedback page.** Likes and dislikes with their notes, question and trace; a reviewer can propose an example from one disliked or failed run, which runs the same proposal code as `propose_examples.py` (§11 step 8).
- **Evaluation page.** Reads `eval_reports`: per-layer rates, the threshold result, the required question categories and failed cases. An `admin` can start a run of the active pack's eval set: it is labelled as using paid AI, asks for confirmation, runs one at a time per pack inside `api`, and stores its report like `eval.py`.
- **Users page** (team mode only). Lists accounts with their roles and status; an `admin` creates accounts, resets passwords, changes roles and disables or enables users as set in §9.
- **Costs page.** LLM cost by day, alias, model, tier and provider from `llm_calls`, always labelled as an estimate.
- **Models page** (`admin`). Lists the providers with whether a key is set, and the model tiers with their current model and its latest eval result for the pack, or "not evaluated". An `admin` adds, tests and removes providers and maps a tier to any model of a configured provider (§2). Each change is written to `agent_logs.admin_actions`.
- **Audit page.** Shows the access decisions of `audit` and the input-screening verdicts of `input_screening`.
- **Sample-data mode.** Each web feature reads either the real api or the active pack's `sample_data/`, chosen per feature in one place. A feature on sample data shows a Sample data badge, so a demo is never mistaken for a real answer. The public demo is the web app built with every feature on sample data and no backend. Sample data belongs to the pack, is hand-written and is never copied or derived from a licensed dataset; the engine code in `apps/web` stays free of pack names. Each phase plan's Web wiring section names the features it moves to the real api.

## 16. Transition from v3

The code built in Phases 0 to 12 follows v3. Each row is replaced by the phase named; until then the v3 behaviour stays in place and working.

| v3 behaviour still in the code | v4 decision | Phase |
|---|---|---|
| Settings and secrets in `.env` | App state in SQLite with encrypted secrets, setup state, numbered schema changes (§2, §3) | 13 |
| LiteLLM Proxy service, catalog aliases, OpenAI embeddings, eval-gated providers, classifier always on | LiteLLM SDK in `api`, providers in the app state, local embeddings, optional classifier (§2, §9) | 14 |
| Keycloak sign-in, sessions in the web process, roles from the JWT | Individual and team modes with local accounts and optional OIDC (§9) | 15 |
| Six Compose services | One image and one container; Qdrant runs as an internal process until Phase 20 (§3) | 16 |
| Sources declared only in manifests, credentials from `.env`, manual full reloads | Sources page, named collections created with SQL, scheduled and incremental copies (§4, §15) | 17 |
| No SQL Server source | SQL Server through ODBC (§4) | 18 |
| Marts hand-written in dbt, pack usable only after review and eval | Instant pack (§11) | 19 |
| Qdrant | Search in ClickHouse, documents optional (§2, §5) | 20 |
| 90-day expiry of conversations, one worker, development datasets in the image | Retention split, hardening, release and demo (§3, §14) | 21 |
