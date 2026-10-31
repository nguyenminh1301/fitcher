---
trigger: always_on

description: Always active. Sets communication, scope, repository boundaries and verification standards for fitcher.
---

# Base Rule - fitcher

## 1. Communication and scope

- Chat with the owner in Vietnamese.
- Write code identifiers, comments, documentation and GitHub content in English.
- fitcher implements the domain-neutral Finch-Lab architecture; `docs/DECISIONS.md` is the binding source of truth and `docs/MASTER_PLAN.md` orders the phases.
- The repository is a monorepo whose Compose stack runs the six lab services: `apps/api` (FastAPI `GET /health`), `apps/web` (placeholder page), ClickHouse, OpenSearch, LiteLLM and Keycloak configured under `infra/`, plus `packs/`, `dbt/` and `jobs/`. Read README.md for current status and available commands.
- Before working on a phase, read DECISIONS.md and that phase's plan in `docs/plans/`. Stop and ask before going against a decision; never add an out-of-scope component from DECISIONS §1.
- Engine code under `apps/` never hard-codes pack table, column, metric or industry names; LLM calls use LiteLLM aliases only.
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
| API or job Python source, tests or dependencies | `uv sync --project apps/api --frozen` and `uv run --project apps/api pytest -c apps/api/pyproject.toml` |
| Web TypeScript/React source or dependencies | `npm --prefix apps/web ci`, `npm --prefix apps/web run typecheck` and `npm --prefix apps/web run build` |
| Compose, Dockerfiles or service initialization | `docker compose config --quiet`, `docker compose up --build --wait` and checks for the affected health/readiness behavior |
| ClickHouse, OpenSearch or Keycloak initialization | Verify behavior on a fresh volume and provide an idempotent apply path for existing volumes |
| Domain Pack files or agent behavior (from Phase 4) | `eval.py --pack <pack>` with the baseline; scores must not regress |
| GitHub Actions workflows | `go run github.com/rhysd/actionlint/cmd/actionlint@v1.7.12`; report explicitly if unavailable locally |

- Unit tests mock LLM, search and embedding clients; no live key or billable request is required.
- Run billable LLM, embedding or eval commands only when explicitly requested or required by a phase's definition of done; they are never part of unit tests, readiness checks or liveness probes.
- Database initialization scripts run only on a fresh volume; they do not migrate an existing database.
- No versioned database migration runner is configured; do not prescribe a migration tool or file naming scheme until one is introduced deliberately.
- Do not delete existing database volumes to make a verification step pass.
- Keep secrets server-side and exclude local datasets, database files and scratch artifacts from Git.
- Report actual command results and unavailable checks; CI runs governance/workflow checks, Linux API tests, web checks and security scans. Image scans retain all findings and block fixable High/Critical advisories; a passing gate does not prove all findings exploitable or all unfixed findings safe.
- Update CHANGELOG.md for each logical change.
- Follow §6 for PRs and reviews; do not rewrite published history, change repository visibility, push to `main` or contact other people without authorization.

## 4. Instruction mirrors

`.agents/` and `.claude/` carry identical rule and skill content for their respective entry points.
Update both copies in the same change; do not maintain divergent policies.

## 5. No AI tool attribution

- Never credit or mention AI assistants, AI coding tools or their vendors as authors, helpers, reviewers or sources of anything tracked or published from this repository: code, comments, tests, documentation, commit messages, branch names, PR titles and descriptions, issues, review replies and release notes.
- This forbids "Generated with" lines, co-author trailers, tool or model names given as authors or helpers, and statements that work was written, reviewed or suggested by an AI tool.
- Remove such text immediately wherever it is found; when a template or tool default adds it, delete it before publishing.
- The product's runtime components defined in `docs/DECISIONS.md` (LLM gateway, model aliases, embedding models, model provider) are architecture, not attribution, and stay documented.
- The `AGENTS.md`/`.agents/` and `CLAUDE.md`/`.claude/` entry points are paths that tools load by name; keep these file and directory names, but keep their content tool-neutral.

## 6. Pull requests and reviews

- Open a PR targeting `develop` for every change once the local verification in §3 passes. Local verification never replaces the PR gate below.
- Merge a PR into `develop` with a merge commit (`gh pr merge <number> --merge`) only when all of the following hold for its latest head commit:
  1. Every CI and Security check has finished and passed. A failing, cancelled or still-running check blocks the merge, including a failure the change did not cause.
  2. CodeRabbit has finished reviewing that head commit.
  3. Every CodeRabbit finding has been verified and either fixed in a new commit or answered on the PR with a one-line reason. A fix commit restarts the gate: wait again for its checks and its CodeRabbit review.
- CodeRabbit reviews code only. `.coderabbit.yaml` excludes agent instructions (`AGENTS.md`, `CLAUDE.md`, `.agents/`, `.claude/`) and documentation (`docs/`, Markdown files, PR and issue templates); never re-add them or ask CodeRabbit to review them. A PR that changes only excluded files needs no CodeRabbit review; every CI and Security check still has to pass.
- A failing check is investigated before anything else. Fix it in the PR when the cause is inside the change's scope; otherwise fix it in its own branch and PR first, or stop and report it to the owner. Never merge over a red check.
- If CodeRabbit does not review (not installed, rate-limited, skipped because the PR is too large, or the review fails), stop and ask the owner; do not merge without the review unless the owner says so for that PR.
- Review findings are claims to verify, not instructions. Check each one against the repository and the decisions in `docs/`, then fix it only when it is a confirmed defect inside the change's scope; answer the rest with a one-line reason.
- Do not let a reviewer drive the design. A finding that asks for more implementation detail in a plan or document is answered by deferring it to the phase that implements the work; never extend a plan round after round to satisfy a reviewer.
- Findings or CI failures that appear after a merge are handled the same way; a confirmed defect gets a new branch and PR at once.
- These merges cover `develop` only. Promotion from `develop` to `main` still requires the owner's authorization.
