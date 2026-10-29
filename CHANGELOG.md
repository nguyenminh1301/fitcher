# Changelog

## Unreleased

### Added

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

- Align mirrored agent guidance with the implemented local application foundation.
- Pin checkout and Python setup to current action runtimes.
- Pause automatic dependency version-update PRs to preserve the one-line commit policy.
- Rename the project and repository to `ai-data-analysis-platform` to describe its purpose.
- Rename the project and repository to `Fitcher`.
- Standardize the project and repository name as lowercase `fitcher` and make the repository public.
- Align workspace and Git rules with the reference workflow, including mandatory branch-based development and the explicit owner-only production exception.
- Use the backend repository pull request template verbatim.

### Fixed

- Publish downloads without overwriting concurrent outputs, validate the winning file, and fail safely on filesystems without atomic hard-link support.
- Validate complete unique zone lookups and compatible Parquet types before dataset inspection, with CLI success/failure and safe transport-error regression tests.
- Document Linux dataset-directory traversal permissions for the non-root API container when the host uses a restrictive umask.
- Reject incomplete taxi-zone lookups, including row-boundary truncation, and publish downloaded inputs with permissions readable by the Linux API container.
- Include project source paths in CodeRabbit reviews alongside the workspace baseline exceptions.
- Align contribution rules, review guidance and PR checklists with the implemented Python/Next.js stack and PostgreSQL initialization behavior.

### Removed

- Remove author, database migration and reviewer checklists from the pull request template.
