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
| 7 | [API and streaming](plans/phase-07-api-and-streaming.md) |
| 8 | [Conversation](plans/phase-08-conversation.md) |
| 9 | [Chat and chart frontend](plans/phase-09-chat-and-charts-frontend.md) |
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
  - Database `agent_logs` with 7 tables, a dedicated user and TTL
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

## Phase 7: API and streaming

- **Goal:** expose the agent through the API.
- **Deliverables:**
  - FastAPI: JWT verification, role mapping, trace_id creation, in-process rate limiting
  - SSE endpoint `/ask`, following the event order in DECISIONS §6
  - Pydantic schemas for QuerySpec, Result and ChartSpec; TypeScript types generated from them
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
- **DoD:**
  - "What about last year?" uses the previous turn's QuerySpec
  - "Draw it as a line" generates no SQL
  - An ambiguous question returns clarify
  - The eval set gains the corresponding question groups

## Phase 9: Chat and chart frontend

- **Goal:** the end-user interface.
- **Deliverables:**
  - Next.js: OIDC login, SSE chat, per-step status display
  - Data table (TanStack)
  - SQL view
  - Warning display
  - Clarify shown as buttons
  - Chart rules on the backend
  - ChartSpec -> ECharts adapter
  - Chart type switcher (invalid types disabled)
  - PNG and CSV export
  - Like/dislike buttons writing to `feedback`
- **DoD:**
  - The acceptance question shows a grouped bar
  - Switching between bar / table / line makes no API call
  - A pie chart is never shown for a time series

## Phase 10: Automated onboarding

- **Goal:** generate a pack for a new company automatically, with human review.
- **Deliverables:**
  - `profile.py`
  - `ingest_docs.py`: parse, chunk, load into `kb_docs`
  - `draft_pack.py`: drafts with `evidence` and `confidence`
  - Review UI in web: approve / edit / delete each item, test-run metrics, write approved YAML
  - Compile the pack after review
- **DoD:**
  - After deleting the descriptions from the hand-written pack, letting the drafter regenerate them and reviewing them, the eval score is not significantly lower than the hand-written pack's

## Phase 11: Industry neutrality proof

- **Goal:** plug the system into a different industry without changing the engine.
- **Deliverables:**
  - Onboard the second dataset (Iowa Liquor Sales or Maycee) using only the Phase 10 pipeline
  - A dedicated `eval.yaml` for this pack
- **DoD:**
  - The new pack runs with **0 changed lines** in `apps/api` and `apps/web`
  - It reaches the configured eval threshold

## Phase 12: Admin, audit and feedback loop

- **Goal:** observe the system and improve it over time.
- **Deliverables:**
  - Admin UI:
    - run list by user / date / status
    - trace detail view
    - denied audit view
    - LLM cost view
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
