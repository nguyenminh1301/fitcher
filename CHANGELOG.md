# Changelog

## Unreleased

### Added

- Read a whole agent run with one query: the `agent_logs.trace_query_log` view exposes `system.query_log` rows by trace id to the trace reader, `infra/clickhouse/queries/trace.sql` lists the run row, node events, LLM calls, SQL attempts and query-log entries of a trace in time order with incomplete runs marked `INCOMPLETE` and LLM calls sent compared with those logged, and `docs/tracing.md` explains how to read it.
- Store every eval run's JSON report in `agent_logs.eval_reports` with its pack, execution match rate and whether it passed; a failed write is reported on stderr and leaves the exit code unchanged.
- Record every LiteLLM proxy call in `agent_logs.llm_calls` through a custom callback mounted into the proxy: alias, resolved model, call id, tokens, cost, latency, status and error, tagged with the trace id and graph node the api sends as request metadata.
- Log node events and SQL attempts for every run of `jobs/ask.py` and `jobs/eval.py`: each graph node writes its start, end, status and state update as JSON capped at 16 KB with result rows reduced to counts, and each executed query writes its SQL, attempt number, `query_id`, row count and error to `sql_runs`; the api service gets the log writer password and `LOG_*` settings.
- Trace every agent run with OpenTelemetry: the run's 32-hex trace id replaces the generated UUID in graph state, `log_comment` and eval case scores; LLM and embedding requests inside a run carry its trace id and current node as LiteLLM metadata and are counted; with a log writer, `run_question` writes a `running` row before the graph and a final row with status, latency, LLM call count, lost records and `log_complete` after flushing the run's records.
- Write `agent_logs` records from the api with `app.observability.log_writer`: run rows insert synchronously, other records go through a bounded queue that a background thread flushes in per-table batches at `LOG_BATCH_SIZE`, every `LOG_FLUSH_INTERVAL_MS` and on request, retrying a failed batch with the same insert deduplication token, and counting each trace's records as written or lost (full queue, failed batch or flush timeout) without ever failing the run.
- Add three configuration-defined ClickHouse users for `agent_logs`: `agent_logs_writer` may only insert, `agent_logs_trace_reader` may read the run, node, LLM, SQL, audit and eval tables plus `system.query_log`, and `agent_logs_review_reader` may read proposed examples, feedback and chat messages, both readers under 30-second and 100,000-row limits a query cannot change; `agent_readonly` gets no access, and each password is a required `.env` value.
- Create the ClickHouse `agent_logs` database for run logs: `runs` (latest row per trace), `events`, `llm_calls`, `sql_runs`, `audit`, `chat_messages`, `feedback`, `eval_reports` and `example_proposals`, each expiring rows after 90 days and accepting insert deduplication tokens; `initdb` creates them on a fresh volume and `jobs/apply_log_schema.py` applies the same idempotent DDL to an existing one.
- Record the `ecommerce_twin` eval baseline in `packs/ecommerce_twin/eval_baseline.json` and `docs/eval/ecommerce_twin-baseline.md`: execution matches 10 of 22 scored cases (45%), below the 80% pack threshold, with the agent behaviors behind the failing cases listed for the phases that fix them.
- Grow the `ecommerce_twin` eval set to 31 labelled questions, at least three per DECISIONS §12 category: 22 answered `data_query` cases with reference SQL checked against the marts as the read-only agent user, and 9 clarify, deny and out-of-scope cases kept for the phases that build those branches; retrieval labels name only the columns retrieval must find, not the time column the agent takes from the dataset definition.
- Score a pack's eval set from the command line with `jobs/eval.py --pack <name>`: it runs the approved cases against the compiled pack named by `--pack` at temperature 0, prints the Markdown report, writes Markdown and JSON with `--output-dir`, compares with `--baseline`, and exits 0, 1 on a regression or below the 80% execution threshold, or 2 on a setup or reference-query error.
- Render an eval run as Markdown (per-layer and per-category rates, a per-case table with the failure reason, reference errors) and JSON with `app.eval.report`, and compare it with a baseline run: a layer regresses when its pass count over the cases both runs scored drops by more than one, and the pack meets its threshold when the execution match rate reaches it.
- Run an eval set through the agent graph one case at a time with `app.eval.runner`: each active case first gets its reference result from `expected_sql` on the read-only ClickHouse user or from `expected_rows`, then asks its question under its own trace id and a per-case time limit; a failing reference query, an exception or a timeout fails that case without stopping the run.
- Reject an eval case whose `expected_rows` do not all name the same columns as the first row.
- Score an eval case per layer from the final graph state: extraction matches the resolved periods, `top_n` and `rank_by` exactly, retrieval reports the recall of the labelled dataset and columns among the retrieved hits, execution compares the answer with the reference result, intent waits for the router, and cases of unbuilt branches are reported as not yet scored.
- Compare an eval answer with its reference result by column values: key and measure columns match whatever their names or positions, extra answer columns are allowed, rows align by key and keep their order only for ranked cases, and numbers match within a relative tolerance of 1e-6 and an absolute one of 1e-9.
- Let eval cases give their reference result as inline `expected_rows` instead of `expected_sql` (never both), and the eval set a fixed `reference_date`; `app.eval.cases` loads the approved cases, reports cases for unbuilt branches as inactive and rejects an active case that is not an answered `data_query` with a reference result.
- Add the Fitcher finch mascot in `docs/brand/mascot/`: a geometric bird with a left-leaning chest point, in black and white SVG and 1024 px PNG, listed in the brand guide as an illustration rather than a logo.
- Add the Fitcher brand kit in `docs/brand/`: a symbol of table cells forming an F with an answer dot, a custom outlined wordmark, horizontal and stacked lockups, light and dark GitHub README banners, favicon and app icons, and a usage guide with the black, white and grey palette.
- Answer `data_query` questions from the command line with `jobs/ask.py`: a LangGraph flow extracts terms and period descriptors through `fast`, resolves periods, retrieves pack context from the six indices, maps terms to metrics, columns and values with the pack's conventions and a coverage check, generates SQL through `sql-gen` with up to three repairs (the third through `sql-gen-hard`), guards and runs it as the read-only user, types the result from the compiled catalog and summarizes the rows in the question's language; questions with no measure or period, or an ambiguous measure, are refused before any SQL is generated.
- Fail CI when a dataset id, column name or metric id of any pack appears in `apps/api`, tests included, except the names of the synthetic fixture pack.
- Run agent SQL on ClickHouse as a read-only `agent_readonly` user granted only `marts`, whose profile caps the per-query time, row and memory limits; every query carries `log_comment = trace_id` and a generated `query_id`, runs `EXPLAIN` first, and its errors are classified as `sql`, `runtime` or `policy` for the retry loop.
- Guard generated SQL with sqlglot: exactly one read query (SELECT, set operations, CTEs) over allowlisted `marts` tables and columns, no table functions, external-access, dictionary or sleep functions, `system` tables, `SELECT *` on datasets or `SETTINGS`/`FORMAT` clauses, and an outer LIMIT added or capped; rejections are policy errors and unparsable SQL is an `sql` error to retry.
- Call the LiteLLM chat aliases `fast`, `sql-gen` and `sql-gen-hard` through one client that refuses model names, requests JSON-schema output validated into Pydantic models or plain text, and reports gateway failures without leaking replies; tests use a scripted fake client.
- Resolve extracted period descriptors (year, quarter, month, explicit range, relative unit, unit to date and last N units) into labelled half-open date ranges using the pack's fiscal calendar, with fiscal years named by their end year, ISO weeks and the user's time zone for today, falling back to UTC.
- Define the `QuerySpec` and `Result` contracts with half-open periods, bounded `top_n`, known filter operators, consistent ranking and comparison fields, and row, column and truncation checks capped at 5,000 rows.
- Compile a Domain Pack with `jobs/compile_pack.py`: validate it against the ClickHouse marts, keep approved items, test-run every metric read-only, record dataset date coverage, and publish a new generation of six pack-scoped OpenSearch indices with role-filtered documents, diacritic-folding text, `embed` vectors for hybrid BM25 + kNN search and fuzzy column values, moving all aliases in one request and writing `compiled.json` to a volume the API reads; a failed compile leaves the live generation untouched.
- Add the hand-written `ecommerce_twin` Domain Pack over the three marts: a USD business profile without time zone or answer language, with the "best-selling = net sales" convention, column roles and indexable string columns, ten metrics, Vietnamese and English glossary aliases, the returns join path, analyst and marketing roles, few-shot examples and one seed eval case per required category, with a test that loads every pack against the dbt mart columns.
- Check Domain Pack cross-references: unique ids, metric, dataset, column and role references across files, time columns, indexable string columns, dataset `allowed_roles` equal to the roles `policies.yaml` grants, and dataset tables and columns against a warehouse catalog.
- Define the Domain Pack format as one JSON Schema per pack file with shared id, status, evidence and confidence definitions, load packs into matching Pydantic models with YAML 1.2 scalars, and report every invalid file, missing or unknown field and bad enum value with its file and item path.
- Document the marts refresh, refresh-state protocol, stale-lock recovery and acceptance query, and select the acceptance analysis by name in the Phase 1 verification command.
- Build the `sales_lines`, `returns_fact` and `sessions_daily` marts from typed staging views with key, relationship, date-range and non-negative tests, and answer the Q1 2024 versus Q1 2025 top-10 products question in SQL with a test that recomputes it from staging.
- Refresh a source under a per-source lock table, loading its raw tables and building its dbt models and tests, and record each generation as started, completed or failed in `data_meta.refresh_log` so readers can tell a complete refresh from a partial one.
- Add the dbt project with an environment-driven ClickHouse profile, pinned dbt-core and dbt-clickhouse in the jobs image, per-source model tags and checks that every source folder carries its `dbt_tag` and no model sets an alias.
- Run data jobs in a `jobs` Compose service on the `api` image that alone holds the ClickHouse admin credentials and mounts `./data`, and document loading the CC BY-NC 4.0 lab dataset.
- Load a manifest source into ClickHouse `raw` tables from its pinned Hugging Face revision, publishing every table only after all row counts match and leaving the previous tables untouched on any failure.
- Validate source manifests for raw data loads, including pinned revisions, expected row counts, optional load-time date ranges with dataset-card counts, safe identifiers and a `dbt_tag` unique across sources, with the e-commerce lab dataset manifest.
- Run ClickHouse, OpenSearch, LiteLLM and Keycloak beside the API and web skeletons in Docker Compose with pinned images, loopback ports, health checks, the `raw`/`marts`/`data_meta` databases, a disabled ClickHouse `default` user, the four LiteLLM model aliases, a placeholder `finch` realm, Make targets and a billable `fast` alias smoke job.
- Forbid AI tool attribution in code, documentation, commits, branches, PRs, issues and review replies, and extend the commit message and PR title check to more tool names.
- English settled decisions for the domain-neutral Finch-Lab architecture, its master plan and a detailed plan for each delivery phase.
- Linux API/CLI tests, web typecheck/build, dependency and Git-secret audits, and weekly runtime-image security scans with complete report artifacts and fixable High/Critical gates.
- Official TLC HVFHV and taxi-zone downloads with atomic publication, validated cache reuse, Uber-only DuckDB views and three sample analysis queries with real-data verification.
- Local Next.js and FastAPI foundation with a liveness endpoint, locked dependencies, three-service Docker Compose setup, pgvector initialization and an explicit OpenAI Responses connectivity check.
- API health and OpenAI smoke-command tests covering missing credentials, safe error diagnostics and incomplete responses.
- Shared durable naming and explanation rules for all tracked project artifacts.

- Per-developer workspace structure, task continuity guidance and mirrored agent rules.

- Repository ownership, issue and pull request templates, contribution and security policies.
- CodeRabbit configuration for the planned Python/Next.js stack and both integration and production branches.
- Executable commit, PR title and branch policy checks, repository checks and workflow lint.
- Prepared GitHub Actions dependency update configuration and advisory PR size labels.
- Development and production branch rules, English project documentation and planned OpenAI environment settings.

### Changed

- Raise the `ecommerce_twin` eval baseline to 20 of 22 execution matches (91%, above the 80% pack threshold) after the ranking and extraction fixes, with the remaining failures listed in `docs/eval/ecommerce_twin-baseline.md`.
- Let the LLM client send a fixed `temperature` with every call, and have the LiteLLM proxy drop request parameters a model rejects (`drop_params`), so eval runs can ask for temperature 0 on any model.
- Settle the Phase 4 eval decisions: result sets match columns by value and allow extra columns, a pack needs execution match of at least 80% of active eval cases, eval runs request temperature 0, and a regression is a drop of more than one case per layer over the cases both runs scored.
- Plan company documents as runtime content: reviewers upload PDF, DOCX, Markdown, text and XLSX files on a Documents page and delete them at any time, with stored originals, a `data_meta.documents` registry, role-scoped `kb_docs` chunks and compiles that carry documents into each index generation.
- Take the user's time zone from the browser with each request (UTC for clients that send none) and answer in the language of the question, instead of fixing both in the pack's business profile.
- Limit CodeRabbit to code by excluding agent instructions and documentation from its review, and let PRs that change only those files merge on passing checks without a CodeRabbit review.
- Settle the Phase 1 data plan from the inspected lab dataset: date-only typing, net sales without discounts, all-or-nothing raw publication, refresh state with a generation check for readers, unique `dbt_tag` values and a `jobs` Compose service that keeps admin credentials out of `api`.
- Merge pull requests into `develop` only after every CI and Security check on the latest head commit passes and CodeRabbit has reviewed it with every finding verified and fixed or answered, treat a failing check as blocking even when the change did not cause it, and ask the owner when CodeRabbit does not review.
- Align mirrored agent rules, entry points, review configuration, contribution and security guidance, README and the PR template with the domain-neutral architecture, and add the `pack` and `infra` commit scopes.
- Move the API and web skeletons into `apps/api` and `apps/web` and add documented `packs/`, `dbt/`, `jobs/`, `infra/` and prompt directories for the monorepo layout.
- Build patched runtime images without API/web language package managers and run PostgreSQL directly as its database user while preserving existing named volumes.
- Remove Corepack from the web runtime so it cannot bootstrap language package managers.
- Aggregate pickup counts before joining zone labels to reduce work while preserving unmatched locations, null IDs and deterministic ties.
- Align mirrored agent guidance with the implemented local application foundation.
- Pin checkout and Python setup to current action runtimes.
- Pause automatic dependency version-update PRs to preserve the one-line commit policy.
- Rename the project and repository to `ai-data-analysis-platform` to describe its purpose.
- Rename the project and repository to `Fitcher`.
- Standardize the project and repository name as lowercase `fitcher` and make the repository public.
- Align workspace and Git rules with the reference workflow, including mandatory branch-based development and the explicit owner-only production exception.
- Use the backend repository pull request template verbatim.

### Fixed

- Extract questions with `extract.v2`: a term naming a specific value ("premium members", "nhóm hàng Furniture") is a filter rather than a breakdown, naming or comparing periods no longer sets a time grain, offsets for a period named relative to another one count from the current unit, and a ranking word is left empty when the question names its measure.
- Rank a "top N" question by the measure it names ("Top 5 brands by units sold", "doanh thu cao nhất") instead of refusing the vague ranking word; a ranking word with no measure is still refused.
- Open the read-only agent ClickHouse client without a session, so a query left running by a timed-out eval case cannot lock the client for the next case.
- Pair eval result rows that share a key by their mapped measure values, so reordered measure columns no longer fail a matching unordered result.
- Report an eval set whose `reference_date` is not a real calendar date as an eval-set error instead of an unhandled `ValueError`.
- Reject a key repeated within one mapping of a Domain Pack YAML file instead of silently keeping its last value.
- Correct the translated SQL retry rule and branch-specific SSE sequences, and make the phase plans define atomic index publication, a no-partial-data refresh requirement, permission revocation, trace completeness, credential-free realms and redaction of feedback proposals.
- Publish downloads without overwriting concurrent outputs, validate the winning file, and fail safely on filesystems without atomic hard-link support.
- Validate complete unique zone lookups and compatible Parquet types before dataset inspection, with CLI success/failure and safe transport-error regression tests.
- Document Linux dataset-directory traversal permissions for the non-root API container when the host uses a restrictive umask.
- Reject incomplete taxi-zone lookups, including row-boundary truncation, and publish downloaded inputs with permissions readable by the Linux API container.
- Include project source paths in CodeRabbit reviews alongside the workspace baseline exceptions.
- Align contribution rules, review guidance and PR checklists with the implemented Python/Next.js stack and PostgreSQL initialization behavior.

### Security

- Record the pyasn1, pypdf and py3-pip-wheel advisories published after the LiteLLM v1.106.6 pin as expiring image exceptions, because no newer stable LiteLLM release fixes them.
- Scan the four pinned third-party service images in the image audit with the same fixable High/Critical gate and complete reports, with per-image expiring exceptions for advisories only an upstream release can fix, and validate the Compose file in CI.

### Removed

- Remove the TLC HVFHV download, DuckDB views, sample queries, PostgreSQL/pgvector service and OpenAI smoke check, which the domain-neutral ClickHouse architecture replaces.
- Remove the TLC dataset guide, superseded by the domain-neutral architecture decisions.
- Remove author, database migration and reviewer checklists from the pull request template.
