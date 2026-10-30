---
trigger: always_on

description: Always active. Sets communication, scope, repository boundaries and verification standards for fitcher.
---

# Base Rule - fitcher

## 1. Communication and scope

- Chat with the owner in Vietnamese.
- Write code identifiers, comments, documentation and GitHub content in English.
- fitcher includes a local Next.js/FastAPI/PostgreSQL foundation with pgvector.
- Local HVFHV downloads and DuckDB dataset views are available. The bounded executor, SQL generation, LangGraph, SSE and chat/chart features remain planned; read README.md for current status and available commands.
- Implement only the requested scope; do not add speculative application code, dependencies or abstractions.

## 2. Working standards

- Read `workspace.md` and the current task's progress before acting.
- Apply `naming.md` to every tracked name and explanation; do not make committed artifacts depend on private task context.
- Inspect applicable rules, current files and Git state; preserve unrelated user changes.
- Adapt imported conventions to the current manifests and source; preserve their presentation without inheriting another stack's commands, architecture or database tooling.
- Use the main checkout, never Git worktrees.
- Load `git_workflow.md` before branches, commits or PRs.
- Use one agent unless delegation is explicitly requested.
- For small, clear documentation/configuration edits, proceed directly without separate design approval or application-test ceremony.
- Preserve Windows/PowerShell and Linux support without changing global toolchains.

## 3. Verification and security

Run checks that cover the changed area; mark unrelated checks as N/A with a reason.
Use Python 3.13 and the pinned uv version for the API, and the Node/npm versions declared by the web app and README.md.
Repository checks alone support Python 3.11 or newer.

| Changed area | Required verification |
|--------------|-----------------------|
| Documentation, rules and repository configuration | `python scripts/check_repository.py` and `python scripts/check_git.py --range origin/develop..HEAD` |
| API Python source, tests or dependencies | `uv sync --project api --frozen` and `uv run --project api pytest -c api/pyproject.toml` |
| Web TypeScript/React source or dependencies | `npm --prefix web ci`, `npm --prefix web run typecheck` and `npm --prefix web run build` |
| Compose, Dockerfiles or service initialization | `docker compose config --quiet`, `docker compose up --build --wait` and checks for the affected health/readiness behavior |
| PostgreSQL/pgvector initialization | Verify extension/schema behavior on a fresh test database and document the upgrade path for existing volumes |
| GitHub Actions workflows | `go run github.com/rhysd/actionlint/cmd/actionlint@v1.7.12`; report explicitly if unavailable locally |

- API tests use isolated/mocked OpenAI transports; no live key or billable request is required.
- Run the explicit live OpenAI smoke command only when requested; it is not part of unit tests, readiness checks or liveness probes.
- `scripts/init_db.sql` runs only when PostgreSQL initializes a new volume; it does not migrate an existing database.
- No versioned database migration runner is configured; do not prescribe a migration tool or file naming scheme until one is introduced deliberately.
- Do not delete existing database volumes to make a verification step pass.
- Keep secrets server-side and exclude local datasets, database files and scratch artifacts from Git.
- Report actual command results and unavailable checks; CI runs governance/workflow checks, Linux API tests, web checks and security scans. Image scans retain all findings and block fixable High/Critical advisories; a passing gate does not prove all findings exploitable or all unfixed findings safe.
- Update CHANGELOG.md for each logical change.
- Follow the PR review requirements in `git_workflow.md`; do not merge, enable auto-merge, rewrite published history, change repository visibility or contact other people without authorization.

## 4. Instruction mirrors

`.agents/` and `.claude/` carry identical rule and skill content for their respective entry points.
Update both copies in the same change; do not maintain divergent policies.

## 5. No AI tool attribution

- Never credit or mention AI assistants, AI coding tools or their vendors as authors, helpers, reviewers or sources of anything tracked or published from this repository: code, comments, tests, documentation, commit messages, branch names, PR titles and descriptions, issues, review replies and release notes.
- This forbids "Generated with" lines, co-author trailers, tool or model names given as authors or helpers, and statements that work was written, reviewed or suggested by an AI tool.
- Remove such text immediately wherever it is found; when a template or tool default adds it, delete it before publishing.
- The product's runtime components defined in `docs/DECISIONS.md` (LLM gateway, model aliases, embedding models, model provider) are architecture, not attribution, and stay documented.
- The `AGENTS.md`/`.agents/` and `CLAUDE.md`/`.claude/` entry points are paths that tools load by name; keep these file and directory names, but keep their content tool-neutral.
