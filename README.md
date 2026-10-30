# fitcher

fitcher is a domain-neutral natural-language data analysis lab.
The planned application answers questions such as "Top 10 best-selling products in Q1 2024 compared with Q1 2025" with validated SQL, tables, charts and summaries over company data loaded into ClickHouse and described by a Domain Pack.

## Current status

The repository is a clean monorepo scaffold with no business logic yet.
FastAPI in `apps/api` exposes `GET /health`, Next.js in `apps/web` serves a placeholder page, and Docker Compose runs both.
`packs/`, `dbt/`, `jobs/`, `infra/` and `apps/api/prompts/` contain only READMEs describing what each phase adds.

The architecture is settled in [DECISIONS.md](docs/DECISIONS.md) and delivered in the order of the [master plan](docs/MASTER_PLAN.md), with one [detailed plan per phase](docs/plans/README.md).
Phase 0 (six lab services, LiteLLM aliases, `make up` / `make down`) is next.

## Architecture

| Component | Technology | Responsibility |
| --- | --- | --- |
| Web | Next.js, ECharts, TanStack Table | Chat, tables, charts, SQL view, Review and Admin UIs |
| Auth | Keycloak (OIDC) | Users and roles carried in JWTs |
| API | FastAPI, SSE | Authenticated requests and streamed results |
| Agent | LangGraph, sqlglot | Extract, retrieve, generate, guard, execute and summarize |
| LLM gateway | LiteLLM Proxy (OpenAI) | Aliases `fast`, `sql-gen`, `sql-gen-hard`, `embed` |
| Data and logs | ClickHouse | `raw`, `marts` and `agent_logs` databases, role-based access |
| Retrieval | OpenSearch | Hybrid BM25 + kNN over pack indices |
| Transform | dbt-clickhouse | Raw tables to wide marts |
| Packs | YAML + JSON Schema | Per-company profile, datasets, glossary, metrics, policies and eval |
| Deployment | Docker Compose | Six long-running services plus jobs |

Only `api` and `web` run today; the other services arrive in Phase 0.

## Run locally

Install Docker with Compose v2 (`--wait` support). Host Node/Python are optional when using Docker.
Run these commands from the repository root.

```bash
docker compose up --build --wait
docker compose ps
```

Open [the web app](http://localhost:3000), [API health](http://localhost:8000/health) or [API docs](http://localhost:8000/docs).
`GET /health` returns `200` and `{"status":"ok"}` as a liveness probe; it calls no other service.
Ports bind to loopback. Stop services with `docker compose down`.

The scaffold needs no `.env`; [.env.example](.env.example) gains settings as services are added. Never commit `.env`.
An earlier foundation ran a PostgreSQL `db` service with the `fitcher_pgdata` named volume. When upgrading a checkout that still has that container, start once with `docker compose up --build --wait --remove-orphans` so the old container stops and frees port 5432; this removes the container, not the volume. The volume is left untouched, and removing it with `docker volume rm fitcher_pgdata` is an explicit choice for its owner.

Both runtime images apply available OS security updates during their builds and omit language package managers.
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
uv sync --project apps/api --frozen
uv run --project apps/api pytest -c apps/api/pyproject.toml
uv run --project apps/api uvicorn app.main:app --app-dir apps/api --host 127.0.0.1 --port 8000
```

In another terminal:

```bash
npm --prefix apps/web ci
npm --prefix apps/web run typecheck
npm --prefix apps/web run build
npm --prefix apps/web run dev
```

Host and Docker services use the same ports; stop the Compose services before starting host servers.
Commit dependency changes with the corresponding `apps/api/uv.lock` or `apps/web/package-lock.json`.

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
CI also runs the API suite on Linux and the web frozen install, typecheck and production build. Run the same commands locally for application changes.

The Security workflow runs on PRs, integration/production pushes, manual dispatch and a weekly schedule. It audits locked npm/Python dependencies, scans Git history for secrets, and rebuilds/scans both runtime images. Image jobs retain complete JSON reports and fail for High/Critical findings with a published fix; unfixed advisories remain visible for review. See [security policy](SECURITY.md) for triage and scanner limits. These jobs do not configure required status checks or branch protection automatically.

CodeRabbit is configured for `develop` and `main`, skips drafts, and reviews incremental updates without pausing after a fixed number of commits.
The CodeRabbit GitHub App must have access to this repository and a plan that supports the requested reviews.
Configuration alone does not install or authorize the App.
Reviews are advisory: PRs into `develop` are merged once local verification passes, and later findings are fixed or answered in follow-up PRs.
CODEOWNERS and written rules do not themselves enforce branch protection; no branch protection is installed by this bootstrap.

Dependabot configuration is prepared for weekly GitHub Actions updates into `develop`.
Automatic version-update PRs are paused (`open-pull-requests-limit: 0`) because generated commit bodies conflict with the one-line commit policy.
Apply dependency changes on a normal work branch with compliant commits until an explicit bot policy is chosen.
The PR size labeler runs for branches within this repository; fork PRs do not receive a write token.

## Next steps

- Phase 0: Compose the six lab services with health checks and the LiteLLM aliases.
- Phase 1: Load the e-commerce lab dataset into ClickHouse and build the marts with dbt.
- Later phases follow the [master plan](docs/MASTER_PLAN.md); each starts from its [phase plan](docs/plans/README.md).

See [CHANGELOG.md](CHANGELOG.md) for repository changes and [SECURITY.md](SECURITY.md) for vulnerability reporting.

## Agent workspace

Start with [AGENTS.md](AGENTS.md) or [CLAUDE.md](CLAUDE.md), then read the corresponding `workspace.md` and `base.md` rules.
Rules and workspace guidance are mirrored in `.agents/` and `.claude/`; keep both copies identical.
The [.workspace guide](.workspace/README.md) explains the tracked baseline directories and ignored per-developer working content.
Plans, progress, reports, one-off scripts and scratch files stay there; reusable tools stay in tracked root `scripts/`.

The rule wording and presentation follow the [backend workspace rule](https://github.com/luvax-social/backend/blob/develop/.agents/rules/workspace.md), [backend Git rule](https://github.com/luvax-social/backend/blob/develop/.agents/rules/git_workflow.md) and their shared [working-directory](https://github.com/luvax-social/social-media-platforms/blob/main/.agents/rules/WORKING_DIRECTORY.md) and [Git workflow](https://github.com/luvax-social/social-media-platforms/blob/main/.agents/rules/GIT_WORKFLOW.md) rules.
This repository consolidates the applicable shared rules locally and substitutes its actual stack, scopes and checks; it does not depend on a sibling checkout.
Reference repositories provide rule structure and writing style; project-specific commands, component boundaries and database procedures must match the current manifests and source.
