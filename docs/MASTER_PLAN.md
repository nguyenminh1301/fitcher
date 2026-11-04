# Finch-Lab: Master Plan

Each phase has three parts: goal, deliverables and definition of done (DoD). A phase is complete only when its DoD is met; the next phase starts after that.

Every phase follows [DECISIONS.md](DECISIONS.md). Each phase has a detailed plan under [plans/](plans/README.md); a code-level, test-first task plan is written when the phase starts.

Phases are ordered to reach **one end-to-end flow as early as possible**. Each part is deepened afterwards.

| Phase | Detailed plan |
|---|---|
| 0 | [Repository foundation and infrastructure](plans/phase-00-repository-and-infrastructure.md) |
| 1 | [Data and marts](plans/phase-01-data-and-marts.md) |
| 2 | [Hand-written Domain Pack and compiler](plans/phase-02-domain-pack-and-compiler.md) |
| 3 | [Core agent on the CLI](plans/phase-03-core-agent-cli.md) |
| 4 | [Eval harness](plans/phase-04-eval-harness.md) |
| 5 | [Logging and tracing](plans/phase-05-logging-and-tracing.md) |
| 6 | [RBAC and auth](plans/phase-06-rbac-and-auth.md) |
| 6B | [Web app on sample data](plans/phase-06b-web-app-on-sample-data.md) |
| 7 | [API and streaming](plans/phase-07-api-and-streaming.md) |
| 8 | [Conversation](plans/phase-08-conversation.md) |
| 9 | [Chat and chart frontend](plans/phase-09-chat-and-charts-frontend.md) |
| 9B | [Input screening](plans/phase-09b-input-screening.md) |
| 9C | [Search on Qdrant](plans/phase-09c-search-on-qdrant.md) |
| 9D | [Model routing](plans/phase-09d-model-routing.md) |
| 9E | [Data sources](plans/phase-09e-data-sources.md) |
| 10 | [Automated onboarding](plans/phase-10-automated-onboarding.md) |
| 11 | [Industry neutrality proof](plans/phase-11-industry-neutrality.md) |
| 12 | [Admin, audit and feedback loop](plans/phase-12-admin-audit-feedback.md) |

---

## Phase 0: Repository foundation and infrastructure

- **Goal:** set up the monorepo skeleton and the Docker Compose environment.
- **Deliverables:**
  - Directory structure: `apps/web`, `apps/api`, `packs/`, `dbt/`, `jobs/`, `infra/`, `docs/`
  - Compose file with 6 services: clickhouse, opensearch, litellm, keycloak, api (skeleton), web (skeleton)
  - `.env.example`
  - `make up` / `make down`
  - A healthcheck for every service
  - LiteLLM config with 4 aliases: `fast`, `sql-gen`, `sql-gen-hard`, `embed`
- **DoD:**
  - `make up` starts all 6 services, all healthy
  - The `fast` alias can be called through LiteLLM
  - `api /health` returns OK

## Phase 1: Data and marts

- **Goal:** load the primary dataset into ClickHouse and build the wide marts.
- **Deliverables:**
  - `jobs/load_data.py`: load `FreeEcommerceTwin14M` into database `raw`
  - A dbt-clickhouse project building the marts `sales_lines`, `returns_fact`, `sessions_daily`
  - dbt tests: not_null, unique, relationships
- **DoD:**
  - Row counts of every raw table match the dataset card
  - Hand-written SQL for "top 10 products Q1 2024 vs Q1 2025" on `sales_lines` returns the correct result

## Phase 2: Domain Pack (hand-written) and compiler

- **Goal:** define the pack format and load a pack into the system.
- **Deliverables:**
  - JSON Schema for the 8 pack YAML files
  - A complete hand-written pack `packs/ecommerce_twin/`: profile, datasets, glossary (Vietnamese + English), metrics, examples, policies, eval
  - `compile_pack.py`:
    - validates the schema
    - test-runs every `sql_expr`
    - creates the 6 OpenSearch indices named `_v1` with aliases
    - builds the `column_values` index from top-K values
- **DoD:**
  - The pack compiles successfully
  - A broken pack (invalid schema or failing `sql_expr`) is rejected with a clear message
  - Searching "doanh thu" or "net sales" on OpenSearch returns the correct metric
  - Searching a misspelled product name still returns the correct value

## Phase 3: Core agent (CLI, no UI yet)

- **Goal:** run the `data_query` flow end to end.
- **Deliverables:** a LangGraph graph with the nodes:
  - `extract`
  - `resolve_time`: deterministic, supports multiple periods, unit tested
  - `retrieve`
  - `build_spec`
  - `generate_sql`
  - `guard`
  - `explain`
  - `execute`
  - `check` with a retry loop of at most 3 retries
  - `shape_result`
  - `summarize`

  Run with `jobs/ask.py "<question>"`. This phase uses a single read-only ClickHouse user.
- **DoD:**
  - The acceptance question returns correct SQL and a correct result
  - A deliberate SQL error is self-repaired within 3 retries
  - 0 rows -> a warning
  - No table or metric name is hard-coded in `apps/api`

## Phase 4: Eval harness

- **Goal:** measure quality early, before adding more features.
- **Deliverables:**
  - Command `eval.py --pack ecommerce_twin`
  - Per-layer measurement: extract, retrieval recall, execution result match
  - Markdown report
  - An eval set of at least 30 questions covering the required types in DECISIONS §12
- **DoD:**
  - A baseline report exists
  - Every later phase reruns eval; scores must not drop (no regression)

## Phase 5: Logging and tracing

- **Goal:** trace every step of a run.
- **Deliverables:**
  - Database `agent_logs` with the log tables of DECISIONS §10, dedicated users and TTL
  - Async batched log writer inside the api process
  - LiteLLM callback writing to `llm_calls`
  - `log_comment = trace_id` set on execute
  - A view joining `system.query_log`
- **DoD:**
  - For any `trace_id`, one SQL query retrieves everything: nodes, LLM calls, executed SQL and the ClickHouse query_log

## Phase 6: RBAC and auth

- **Goal:** real permissions at all three layers.
- **Deliverables:**
  - Keycloak realm import: roles and sample users
  - The compiler generates from `policies.yaml`:
    - ClickHouse roles/users, GRANT, ROW POLICY, settings profiles
    - aggregate-only views
  - Guard uses a per-role allowlist
  - Retrieval filters by `allowed_roles`
  - `audit` table
  - Denials never enter the retry loop
- **DoD:**
  - The role x dataset matrix test suite passes
  - SQL that deliberately exceeds permissions is blocked by ClickHouse, even with the guard disabled
  - The eval set gains deny questions

## Phase 6B: Web app on sample data

- **Goal:** every screen of the Fitcher web app design, usable before the api phases: each feature runs on the active pack's sample data until its backend phase wires it.
- **Deliverables:**
  - The design's visual system and shared components, light and dark themes, English/Vietnamese interface switch
  - Chat app: conversation sidebar with search and groups, streamed answers with steps, summary, warnings, chart, table, SQL, notices, clarify options and message actions
  - ChartSpec -> ECharts adapter, local chart type switching, PNG and CSV export
  - Workspace console with role-based navigation and every section
  - Typed api client with a sample and a real implementation per feature; TypeScript types generated from QuerySpec and Result
  - Pack-owned sample data with its schemas; the pack isolation check covers `apps/web`
- **DoD:**
  - Every screen of the design opens and works on sample data, in both languages and themes, at desktop and phone widths
  - Every feature on sample data shows the Sample data badge
  - No pack name appears in `apps/web`

## Phase 7: API and streaming

- **Goal:** expose the agent through the API.
- **Deliverables:**
  - FastAPI: JWT verification, role mapping, trace_id creation, in-process rate limiting
  - SSE endpoint `/ask`, following the event order in DECISIONS §6
  - Pydantic schemas for ChartSpec and the stream events; TypeScript types generated from them (QuerySpec and Result since Phase 6B)
  - Web wiring: Keycloak sign-in and the chat stream move from sample data to the api
- **DoD:**
  - Calling with curl and a JWT returns the full event sequence
  - Invalid JWT -> 401
  - A role without permission receives a `deny` event

## Phase 8: Conversation

- **Goal:** handle non-data questions and follow-up questions.
- **Deliverables:**
  - `router` node classifying 4 intents
  - `load_context` reading back from `chat_messages`
  - `clarify` branch, supporting default conventions from `business_profile`
  - `metadata_qa` branch using glossary + `kb_docs`
  - `chart_edit` branch reusing the previous result
  - Conversation endpoints: list, search, pin, rename, personal groups, delete; edit and retry of a turn (DECISIONS §15)
  - Web wiring: the conversation sidebar and edit/retry move from sample data to the api
- **DoD:**
  - "What about last year?" uses the previous turn's QuerySpec
  - "Draw it as a line" generates no SQL
  - An ambiguous question returns clarify
  - The eval set gains the corresponding question groups
  - A user manages only their own conversations, and editing an earlier question replaces the turns after it

## Phase 9: Chat and chart frontend

- **Goal:** real charts and feedback behind the Chat app built in Phase 6B (DECISIONS §15).
- **Deliverables:**
  - Chart rules on the backend (`chart_recommender`) feeding `chart_spec` events
  - `POST /feedback` writing likes and dislikes to `feedback`
  - Web wiring: real ChartSpec and feedback move from sample data to the api
- **DoD:**
  - The acceptance question shows a grouped bar
  - Switching between bar / table / line makes no API call
  - A pie chart is never shown for a time series
  - Switching EN/VI changes the interface, not the answer

## Phase 9B: Input screening

- **Goal:** screen every untrusted input before it reaches an LLM (DECISIONS §9 Layer 0).
- **Deliverables:**
  - EN/VI rules and the local Prompt Guard 2 classifier (ONNX) in `api`, with `jobs/fetch_guard_model.py`
  - The `screen` graph node, the `blocked` stream event and `agent_logs.input_screening`
  - A LiteLLM `pre_call` guardrail that rejects unscreened requests
  - Instructions sent as `system` messages and untrusted content as `user` messages
  - Screening of document chunks and column values at compile
  - `jobs/screen_eval.py` with a benign and an attack set in English and Vietnamese
  - Web wiring: the `blocked` notice
- **DoD:**
  - An attack question in log mode is answered and logged as `block`; in enforce mode it gets the `blocked` notice and no LLM call
  - Without the classifier every question gets the "screening unavailable" notice and no LLM call
  - A request without screening metadata is rejected by the gateway
  - The `screen_eval.py` report is attached; the pack eval does not regress after the prompt split

## Phase 9C: Search on Qdrant

- **Goal:** replace OpenSearch with Qdrant for the six search collections and measure retrieval, documents included (DECISIONS §5).
- **Deliverables:**
  - `qdrant` service replacing `opensearch`; collections with dense and BM25 sparse vectors, RRF fusion, role payload filters and versioned aliases
  - Compiler, `retrieve` and `metadata_qa` on Qdrant; OpenSearch code and configuration removed
  - A retrieval eval for document questions in English and Vietnamese; reranking, heading-aware chunking and cited sources for definition answers
- **DoD:**
  - Retrieval recall on the pack eval set is not lower than on OpenSearch, and the pack eval does not regress
  - Role filters hold: a role never receives a chunk it may not read (live test)
  - Reindexing through a new alias serves no mixed generation

## Phase 9D: Model routing

- **Goal:** answer simple questions with a smaller model and let an admin choose models per tier across providers (DECISIONS §2 Model tiers).
- **Deliverables:**
  - Deterministic complexity rule choosing `sql-small` or `sql-gen`, with escalation on failure
  - A LiteLLM catalog with OpenAI, Anthropic, Gemini and a local Ollama model, each behind its own alias
  - Tier-to-alias mapping read by the api, with defaults from `.env`; per-tier eval results recorded for each alias
  - Models API and console page for an `admin`; Costs split by tier and provider
- **DoD:**
  - The pack eval does not regress with routing on, and the share of SQL generated by `sql-small` is reported
  - An alias that has not passed the pack eval for a tier cannot be assigned to it
  - A tier change takes effect without restarting LiteLLM and is written to `admin_actions`

## Phase 9E: Data sources

- **Goal:** connect a company's data from PostgreSQL, MySQL/MariaDB, MongoDB and CSV/Parquet/S3 files through ClickHouse (DECISIONS §4 Data sources).
- **Deliverables:**
  - Source manifest kinds and modes (`live`, `copy`) in `jobs/sources/`, with read-only source credentials from `.env`
  - A sync job for copy mode and ClickHouse engine definitions for live mode
  - dbt marts over `raw` (copy) or `src_<source>` (live)
  - The `sources` Compose profile with fixture databases and object store
- **DoD:**
  - The same small fixture dataset, served from each source kind in each supported mode, answers the same questions with the same results
  - RBAC holds on marts built over live sources (column grants, row policies, aggregate-only views), checked by a live test
  - No agent role can read a `src_*` database

## Phase 10: Automated onboarding

- **Goal:** generate a pack for a new company automatically, with human review.
- **Deliverables:**
  - A connect step first: the company's sources are declared and synced or attached (Phase 9E)
  - `profile.py` over the marts built from those sources
  - `ingest_docs.py`: parse, chunk, screen (Phase 9B), load into the Qdrant `kb_docs` collection
  - Documents API behind the Phase 6B Documents page: upload PDF/DOCX/MD/TXT/XLSX, list and delete company documents at runtime, each with its `allowed_roles`
  - `draft_pack.py`: drafts with `evidence` and `confidence`
  - `GET /datasets` and the Review API behind the Phase 6B Datasets and Review pages: approve / edit / delete each item, test-run metrics, write approved YAML
  - Compile the pack after review
- **DoD:**
  - After deleting the descriptions from the hand-written pack, letting the drafter regenerate them and reviewing them, the eval score is not significantly lower than the hand-written pack's
  - A document uploaded on the Documents page is found by `kb_docs` search, and after it is deleted search no longer returns it

## Phase 11: Industry neutrality proof

- **Goal:** plug the system into a different industry without changing the engine.
- **Deliverables:**
  - Serve the second dataset (Iowa Liquor Sales or Maycee) from a PostgreSQL source, connected through Phase 9E, and onboard it using only the Phase 10 pipeline
  - A dedicated `eval.yaml` for this pack
- **DoD:**
  - The new pack runs with **0 changed lines** in `apps/api` and `apps/web`, the web app included, on its own sample data
  - No dataset-specific loader: the data arrives through a source manifest only
  - It reaches the configured eval threshold

## Phase 12: Admin, audit and feedback loop

- **Goal:** observe the system and improve it over time.
- **Deliverables:**
  - Admin API behind the Phase 6B console sections:
    - run list by user / date / status
    - trace detail view
    - denied audit view and input-screening verdicts
    - LLM cost view, split by tier and provider
    - Feedback page proposing an example from one run
    - Evaluation page over `eval_reports`, with an admin-started eval run
    - Users page changing pack roles and disabling users through Keycloak
  - A job proposing new examples from disliked or failed runs -> into the Review UI
- **DoD:**
  - A disliked question -> appears as a proposal -> is approved -> passes in the next eval run

---

## Rules for agents

1. Read `DECISIONS.md` before every phase. To go against any decision, stop and ask.
2. Each phase works on its own branch. Start with a detailed plan and write tests before code.
3. After a phase, run `eval.py` (from Phase 4 onward) and attach the report.
4. Never add any component listed under "Out of scope" in DECISIONS §1.
5. Update `DECISIONS.md` whenever an "open" decision is settled.
