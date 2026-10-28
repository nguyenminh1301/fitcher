# fitcher

fitcher is a natural-language data analysis project.
The planned application turns questions into validated SQL and returns tables, charts and summaries over NYC TLC HVFHV Parquet data.

## Current status

This repository contains project documentation and development governance only.
There is no application scaffold, dependency manifest, database or runnable service yet.

## Planned architecture

| Component | Technology | Responsibility |
| --- | --- | --- |
| Web | Next.js, Plotly | Chat, tables, charts and SQL display |
| API | FastAPI, SSE | Requests and incremental results |
| Agent | LangGraph | Retrieve context, generate, validate and repair SQL |
| Query engine | DuckDB | Bounded read-only queries over Parquet |
| Storage | PostgreSQL, pgvector | Dictionary, glossary, vectors and chat history |
| Deployment | Docker Compose | Three services: web, api and db |

## OpenAI models

| Task | Planned model |
| --- | --- |
| Generate and repair SQL | `gpt-6.1-sol` |
| Summaries and chart specifications | `gpt-6-luna` |
| Dictionary, glossary and question embeddings | `text-embedding-3-small` |

The backend will use the OpenAI Python SDK with Responses and Embeddings APIs.
Stored and query embeddings must use the same model and dimensions; the planned pgvector column has 1536 dimensions.
Changing the embedding model requires rebuilding dictionary and glossary vectors.
The backend and ingestion scripts own `OPENAI_API_KEY`; it must never reach the browser or Git history.
The tracked [.env.example](.env.example) documents planned settings; no application consumes them yet.

## Repository workflow

`develop` is the default integration branch; `main` is the production branch.
Start a focused branch from updated `develop`, then open a PR back to `develop`.
The repository owner may deliberately push directly to `main`; this exception does not permit direct implementation commits to `develop`.
The initial governance setup bootstraps `main` and seeds `develop` from the same commit.

```bash
git switch develop
git pull --ff-only
git switch -c chore/common/update-project-setup
```

Read [CONTRIBUTING.md](CONTRIBUTING.md), [Git rules](.agents/rules/git_workflow.md) and [AGENTS.md](AGENTS.md) before making changes.
Commit messages and PR titles use `type(scope): subject`, in English, on one line with no body or trailers, at most 80 characters (target 72).
Types and Project-specific scopes live in [.github/git-policy.json](.github/git-policy.json).
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
There are no application tests, builds or dependency audits until application manifests and code exist.

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

- Scaffold Next.js and FastAPI with pinned runtimes and dependencies.
- Add Docker Compose, PostgreSQL and pgvector.
- Prepare Parquet, dictionary/glossary ingestion and the first question-to-result flow.
- Extend CI, Dependabot and security scanning as runnable components are introduced.

See [CHANGELOG.md](CHANGELOG.md) for repository changes and [SECURITY.md](SECURITY.md) for vulnerability reporting.
