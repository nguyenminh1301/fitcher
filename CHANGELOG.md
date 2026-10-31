# Changelog

## Unreleased

### Added

- Call the LiteLLM chat aliases `fast`, `sql-gen` and `sql-gen-hard` through one client that refuses model names, requests JSON-schema output validated into Pydantic models or plain text, and reports gateway failures without leaking replies; tests use a scripted fake client.
- Resolve extracted period descriptors (year, quarter, month, explicit range, relative unit, unit to date and last N units) into labelled half-open date ranges using the pack's fiscal calendar, with fiscal years named by their end year, ISO weeks and the user's time zone for today, falling back to UTC.
- Define the `QuerySpec` and `Result` contracts with half-open periods, bounded `top_n`, known filter operators, consistent ranking and comparison fields, and row, column and truncation checks capped at 5,000 rows.
- Run agent SQL on ClickHouse as a read-only `agent_readonly` user granted only `marts`, whose profile caps the per-query time, row and memory limits; every query carries `log_comment = trace_id` and a generated `query_id`, runs `EXPLAIN` first, and its errors are classified as `sql`, `runtime` or `policy` for the retry loop.
- Guard generated SQL with sqlglot: exactly one read query (SELECT, set operations, CTEs) over allowlisted `marts` tables and columns, no table functions, external-access, dictionary or sleep functions, `system` tables, `SELECT *` on datasets or `SETTINGS`/`FORMAT` clauses, and an outer LIMIT added or capped; rejections are policy errors and unparsable SQL is an `sql` error to retry.
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

- Reject a key repeated within one mapping of a Domain Pack YAML file instead of silently keeping its last value.
- Correct the translated SQL retry rule and branch-specific SSE sequences, and make the phase plans define atomic index publication, a no-partial-data refresh requirement, permission revocation, trace completeness, credential-free realms and redaction of feedback proposals.
- Publish downloads without overwriting concurrent outputs, validate the winning file, and fail safely on filesystems without atomic hard-link support.
- Validate complete unique zone lookups and compatible Parquet types before dataset inspection, with CLI success/failure and safe transport-error regression tests.
- Document Linux dataset-directory traversal permissions for the non-root API container when the host uses a restrictive umask.
- Reject incomplete taxi-zone lookups, including row-boundary truncation, and publish downloaded inputs with permissions readable by the Linux API container.
- Include project source paths in CodeRabbit reviews alongside the workspace baseline exceptions.
- Align contribution rules, review guidance and PR checklists with the implemented Python/Next.js stack and PostgreSQL initialization behavior.

### Security

- Scan the four pinned third-party service images in the image audit with the same fixable High/Critical gate and complete reports, with per-image expiring exceptions for advisories only an upstream release can fix, and validate the Compose file in CI.

### Removed

- Remove the TLC HVFHV download, DuckDB views, sample queries, PostgreSQL/pgvector service and OpenAI smoke check, which the domain-neutral ClickHouse architecture replaces.
- Remove the TLC dataset guide, superseded by the domain-neutral architecture decisions.
- Remove author, database migration and reviewer checklists from the pull request template.
