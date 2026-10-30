# Changelog

## Unreleased

### Added

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

- Settle the Phase 1 data plan from the inspected lab dataset: date-only typing, net sales without discounts, all-or-nothing raw publication, refresh state with a generation check for readers, unique `dbt_tag` values and a `jobs` Compose service that keeps admin credentials out of `api`.
- Merge pull requests into `develop` as soon as local verification passes, and treat CI and review findings as follow-ups that are verified before they are applied.
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
