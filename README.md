# fitcher

fitcher is a natural-language data analysis project.
The planned application turns questions into validated SQL and returns tables, charts and summaries over NYC TLC HVFHV Parquet data.

## Current status

The local foundation is implemented: Next.js serves an initialization page, FastAPI exposes `GET /health`, and Docker Compose starts PostgreSQL with pgvector enabled.
An explicit smoke command verifies OpenAI connectivity through the Responses API.
Local HVFHV downloads, Uber-only DuckDB views and sample analysis queries are available.
The bounded query executor, SQL generation, `/ask`, SSE, chat and charts are planned and are not implemented yet.

## Run locally

Install Docker with Compose v2 (`--wait` support). Host Node/Python are optional when using Docker.
Run these commands from the repository root.

PowerShell:

```powershell
Copy-Item .env.example .env
New-Item -ItemType Directory -Force data/parquet
```

Bash:

```bash
cp .env.example .env
mkdir -p data/parquet
```

Copy the environment template only on first setup; preserve an existing `.env`.
Set `OPENAI_API_KEY` in `.env` before the explicit OpenAI check; the local services can start without it.
The database defaults are for this local lab only. Ports bind to loopback; keep credentials private.

```bash
docker compose up --build --wait
docker compose ps
```

Open [the web app](http://localhost:3000), [API health](http://localhost:8000/health) or [API docs](http://localhost:8000/docs).
`GET /health` returns `200` and `{"status":"ok"}` as a liveness probe; it does not call OpenAI or query PostgreSQL.
Compose separately waits for database readiness before starting the API.

Check that pgvector is enabled:

```bash
docker compose exec db psql -U fitcher -d fitcher -c "SELECT extname, extversion FROM pg_extension WHERE extname = 'vector';"
```

Substitute your configured database/user if changed.
The initialization script runs on a new volume only; for a pre-existing database, run `CREATE EXTENSION IF NOT EXISTS vector;` as the database owner.

Run one small, billable OpenAI request explicitly:

```bash
docker compose exec api python scripts/check_openai.py
```

The command has a 30-second timeout, no automatic retries, bounded output and exits nonzero on errors or incomplete/empty output.
It reports status without printing credentials, raw API errors or generated text.
Set `OPENAI_SMOKE_MODEL` to a model available to your API project if needed.
After changing `.env`, run `docker compose up -d --wait` to recreate containers with the new settings; a container restart alone does not reload them.

Stop services with `docker compose down`. The `pgdata` named volume persists database contents; the local `data/parquet` directory is mounted read-only into the API.

All three runtime images apply available OS security updates during their builds. API and web images omit language package managers; the database runs directly as `postgres` and retains PostgreSQL 17 and pgvector 0.8.7. The existing named volume is reused without reinitialization. A custom bind-mounted database directory must already be owned by the image's `postgres` UID/GID; the non-root entry point cannot repair ownership. Do not delete an existing volume to resolve permissions.

Refresh base images and OS security packages periodically, then recreate the services:

```bash
docker compose build --pull --no-cache
docker compose up -d --wait
```

`--no-cache` ensures the OS update layer is rerun. Dependency versions still come from the committed lockfiles; changes to base image tags and language runtimes need their own compatibility review.

## Host development and checks

Use Python 3.13, uv 0.13.6, Node 24.21.0 and npm 11.x. Docker pins its own runtimes; host setup does not require changing global versions.
Install [uv](https://docs.astral.sh/uv/getting-started/installation/) if not already available.
From the root, these commands work in PowerShell and Bash:

```bash
uv sync --project api --frozen
uv run --project api pytest -c api/pyproject.toml
uv run --project api uvicorn app.main:app --app-dir api --host 127.0.0.1 --port 8000
```

In another terminal:

```bash
npm --prefix web ci
npm --prefix web run typecheck
npm --prefix web run build
npm --prefix web run dev
```

Host and Docker services use the same ports; stop the Compose services before starting host servers.
To run the explicit OpenAI check on the host, use `uv run --project api python scripts/check_openai.py`; it loads the root `.env`, preserving existing environment variables.
The API tests use an in-memory HTTP transport for OpenAI and require neither a real key nor network calls.
Commit dependency changes with the corresponding `api/uv.lock` or `web/package-lock.json`.

## TLC dataset

Prepare the fixed March 2024 lab dataset from NYC TLC (about 508 MB) and inspect the views:

```bash
uv sync --project api --frozen
uv run --project api python -m scripts.download_tlc
uv run --project api python -m scripts.check_tlc
```

Run these from the root. Valid existing files are reused; partial downloads are not published.
Inputs remain in ignored `data/parquet/`, outside Git. Neither command requires an OpenAI key.

## Planned architecture

fitcher is moving to the domain-neutral Finch-Lab architecture: ClickHouse marts, Domain Packs, OpenSearch retrieval, a LangGraph agent behind LiteLLM aliases, Keycloak roles and a Next.js chat with ECharts.
[Settled decisions](docs/DECISIONS.md) are the source of truth; the [master plan](docs/MASTER_PLAN.md) and [phase plans](docs/plans/README.md) describe delivery order.
The TLC, DuckDB and PostgreSQL components above predate this architecture and are scheduled for removal.

## Repository workflow

`develop` is the default integration branch; `main` is the production branch.
Start a focused branch from updated `develop`, then open a PR back to `develop`.
The repository owner may deliberately push directly to `main`; this exception does not permit direct implementation commits to `develop`.
The owner exception does not authorize automatic integration or synchronizing implementation changes into both long-lived branches.

```bash
git switch develop
git pull --ff-only
git switch -c chore/common/update-project-setup
```

Read [CONTRIBUTING.md](CONTRIBUTING.md), [Git rules](.agents/rules/git_workflow.md) and [AGENTS.md](AGENTS.md) before making changes.
Commit messages and PR titles use `type(scope): subject`, in English, on one line with no body or trailers, at most 80 characters (target 72).
Types and project-specific scopes live in [.github/git-policy.json](.github/git-policy.json).
The initial README commit predates this policy; do not rewrite published history just to rename it.

## Checks

Python 3.11 or newer is sufficient for the local repository checks; they use the standard library.

```bash
python scripts/check_repository.py
python scripts/check_git.py --range origin/develop..HEAD
python scripts/check_git.py --title "chore(common): update project setup"
```

CI validates repository text/structure, commit messages, PR titles, source branches and GitHub workflows.
PR size labels are advisory: XS up to 100 changed lines, S up to 400, M up to 1000, L up to 2000 and XL above 2000.
Keep PRs at most 1000 changed lines where practical and below 100 changed files for review.
CI also runs the API/CLI suite on Linux (including POSIX permission checks) and the web frozen install, typecheck and production build. Run the same commands locally for application changes.

The Security workflow runs on PRs, integration/production pushes, manual dispatch and a weekly schedule. It audits locked npm/Python dependencies, scans Git history for secrets, and rebuilds/scans all three runtime images. Image jobs retain complete JSON reports and fail for High/Critical findings with a published fix; unfixed advisories remain visible for review. See [security policy](SECURITY.md) for triage and scanner limits. These jobs do not configure required status checks or branch protection automatically.

CodeRabbit is configured for `develop` and `main`, skips drafts, and reviews incremental updates without pausing after a fixed number of commits.
The CodeRabbit GitHub App must have access to this repository and a plan that supports the requested reviews.
Configuration alone does not install or authorize the App.
Do not mark a PR reviewed when the App is unavailable, skipped or rate-limited.
CODEOWNERS and written rules do not themselves enforce branch protection; no branch protection is installed by this bootstrap.

Dependabot configuration is prepared for weekly GitHub Actions updates into `develop`.
Automatic version-update PRs are paused (`open-pull-requests-limit: 0`) because generated commit bodies conflict with the one-line commit policy.
Apply dependency changes on a normal work branch with compliant commits until an explicit bot policy is chosen.
The PR size labeler runs for branches within this repository; fork PRs do not receive a write token.

## Next steps

- Add a bounded read-only executor and SQL validator before text-to-SQL generation.
- Establish a golden-set baseline, then add self-healing, semantic retrieval, SSE and the chat UI.
- Extend application checks as the bounded executor and analysis API are introduced.

See [CHANGELOG.md](CHANGELOG.md) for repository changes and [SECURITY.md](SECURITY.md) for vulnerability reporting.

## Agent workspace

Start with [AGENTS.md](AGENTS.md) or [CLAUDE.md](CLAUDE.md), then read the corresponding `workspace.md` and `base.md` rules.
Rules and workspace guidance are mirrored in `.agents/` and `.claude/`; keep both copies identical.
The [.workspace guide](.workspace/README.md) explains the tracked baseline directories and ignored per-developer working content.
Plans, progress, reports, one-off scripts and scratch files stay there; reusable tools stay in tracked root `scripts/`.

The rule wording and presentation follow the [backend workspace rule](https://github.com/luvax-social/backend/blob/develop/.agents/rules/workspace.md), [backend Git rule](https://github.com/luvax-social/backend/blob/develop/.agents/rules/git_workflow.md) and their shared [working-directory](https://github.com/luvax-social/social-media-platforms/blob/main/.agents/rules/WORKING_DIRECTORY.md) and [Git workflow](https://github.com/luvax-social/social-media-platforms/blob/main/.agents/rules/GIT_WORKFLOW.md) rules.
This repository consolidates the applicable shared rules locally and substitutes its actual stack, scopes and checks; it does not depend on a sibling checkout.
Reference repositories provide rule structure and writing style; project-specific commands, component boundaries and database procedures must match the current manifests and source.
