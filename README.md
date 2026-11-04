# fitcher

fitcher is a domain-neutral natural-language data analysis lab.
The planned application answers questions such as "Top 10 best-selling products in Q1 2024 compared with Q1 2025" with validated SQL, tables, charts and summaries over company data loaded into ClickHouse and described by a Domain Pack.

## Current status

The repository runs the six lab services and answers `data_query` questions from the command line.
Docker Compose starts ClickHouse, Qdrant, LiteLLM, Keycloak, the FastAPI skeleton in `apps/api` (`GET /health`) and the Next.js web app in `apps/web`; their configuration lives in [infra/](infra/README.md).
`jobs/` loads the e-commerce lab dataset into ClickHouse `raw` and refreshes it, and [dbt/](dbt/README.md) builds the `sales_lines`, `returns_fact` and `sessions_daily` marts; [packs/](packs/README.md) holds the Domain Pack schemas and the hand-written `ecommerce_twin` pack, which `jobs/compile_pack.py` validates, test-runs and indexes into Qdrant; `jobs/ask.py` runs the LangGraph agent in `apps/api/app/agent` over the compiled pack, with its prompts in `apps/api/prompts/`.

The architecture is settled in [DECISIONS.md](docs/DECISIONS.md) and delivered in the order of the [master plan](docs/MASTER_PLAN.md), with one [detailed plan per phase](docs/plans/README.md).
Phases 1 (lab dataset and dbt marts), 2 (hand-written Domain Pack and compiler), 3 (core agent on the CLI) and 4 (eval harness) are complete: `jobs/eval.py` scores a pack's eval set per layer, and the `ecommerce_twin` eval set has a recorded [baseline](docs/eval/ecommerce_twin-baseline.md). Phase 5 (logging and tracing) is complete as well: every `jobs.ask` and `jobs.eval` run writes its run row, node events, SQL attempts and LiteLLM calls to ClickHouse `agent_logs`, and [docs/tracing.md](docs/tracing.md) shows how to read one trace. Phase 6 (RBAC and auth) is complete: `compile_pack` turns `policies.yaml` into per-role ClickHouse roles, column grants, row policies, aggregate-only views and users; every question runs as one pack role (`--role`), a question the role may not read is denied before any SQL and every access decision is written to `agent_logs.audit`; the Keycloak realm carries the pack roles and lab users. Phase 6B (the web app on sample data) is complete: every screen of the [web app design](docs/design/web-app.md) works on the active pack's sample data in English and Vietnamese, light and dark themes, at desktop and phone widths. That covers the chat app with streamed answers, charts, tables and SQL, and the workspace console with each role's sections. Each feature shows a Sample data badge until its backend phase wires it to the api. Phase 7 (API and streaming) is complete: the api verifies Keycloak access tokens and streams answers from `POST /ask`, and the web app signs users in through Keycloak and streams its chat answers from the api; the other web features keep their Sample data badge until their phase. Phase 8 (conversation) is complete: a router sends each question to the data, definition, chart-edit or out-of-scope branch, follow-ups reuse the previous query, ambiguous questions get a clarifying question with options, every turn is stored per user so the chat sidebar lists, searches, renames, pins, groups and deletes conversations from the api, and an earlier question can be edited or retried. Phase 9 (charts) is in progress: the api chooses each answer's chart by the DECISIONS §8 rules, and likes and dislikes in the chat are stored per answer through `POST /feedback`. Phase 9B (input screening) screens every question with EN/VI rules and a local prompt-injection classifier before any LLM call, in `SCREEN_MODE=log` until the measurement shows the enforcement gate holds; the LiteLLM gateway rejects requests the api did not screen.

## Architecture

| Component | Technology | Responsibility |
| --- | --- | --- |
| Web | Next.js, ECharts, TanStack Table | Chat, tables, charts, SQL view, Review and Admin UIs |
| Auth | Keycloak (OIDC) | Users and roles carried in JWTs |
| API | FastAPI, SSE | Authenticated requests and streamed results |
| Agent | LangGraph, sqlglot | Extract, retrieve, generate, guard, execute and summarize |
| LLM gateway | LiteLLM Proxy (OpenAI, Anthropic, Gemini, Ollama) | Model tiers `fast`, `sql-small`, `sql-gen`, `sql-gen-hard`, `embed` mapped to catalog aliases |
| Data and logs | ClickHouse | `raw`, `marts` and `agent_logs` databases, role-based access |
| Retrieval | Qdrant | Dense vectors of the `embed` tier and BM25 sparse vectors per point, fused with RRF on the server |
| Transform | dbt-clickhouse | Raw tables to wide marts |
| Packs | YAML + JSON Schema | Per-company profile, datasets, glossary, metrics, policies and eval |
| Deployment | Docker Compose | Six long-running services plus jobs |


## Run locally

Install Docker with Compose v2 (`--wait` support) and give Docker about 8 GB of free memory.
Host Node/Python are optional when using Docker. Run these commands from the repository root.

Copy [.env.example](.env.example) to `.env` and replace every `change-me` value. Never commit `.env`.
A provider's catalog aliases load only when its key is set (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, or `OLLAMA_URL` with the `local-models` profile); every service reports healthy without any key.

| Make target | Plain command (PowerShell and Bash) |
| --- | --- |
| `make up` | `docker compose up --build --wait` |
| `make ps` | `docker compose ps` |
| `make logs` | `docker compose logs --follow --tail=200` |
| `make smoke` | `docker compose exec -T api python -m jobs.smoke_llm` |
| `make down` | `docker compose down` |

`make` is optional; the Makefile only wraps these commands. `make down` never removes volumes, so ClickHouse and Qdrant data survive restarts.
`make smoke` sends one tiny billable request to every alias LiteLLM loaded, checking structured output for chat aliases and one vector for `-embed` aliases, and prints only whether each passed; `--alias <name>` limits it.

### Load the lab dataset and build the marts

```bash
docker compose run --rm jobs python -m jobs.refresh_data --source ecommerce_twin
```

The refresh loads the raw tables, runs `dbt build` for the source's staging views, marts and tests, and records the outcome in `data_meta.refresh_log`; see [jobs/](jobs/README.md) for the refresh state and stale-lock recovery.
`python -m jobs.load_data --source ecommerce_twin` loads the raw tables alone.
Jobs run in the `jobs` Compose service (profile `jobs`), which uses the `api` image, mounts `./data` and is the only service holding the ClickHouse admin credentials.
The loader downloads the seven Parquet files of [`ziadatalabs/FreeEcommerceTwin14M`](https://huggingface.co/datasets/ziadatalabs/FreeEcommerceTwin14M) at the revision pinned in `jobs/sources/ecommerce_twin.yaml` into `data/hf/`, reuses complete downloads on later runs, and publishes the `raw` tables only after every row count matches the manifest.
The dataset is licensed CC BY-NC 4.0 for non-commercial use only; downloads and derived data stay in the Git-ignored `data/` directory and are never committed.
On Linux hosts, `./data` must be writable by UID 10001, the non-root user of the `api` image.

### Compile the Domain Pack

```bash
docker compose run --rm jobs python -m jobs.compile_pack --pack ecommerce_twin
```

The compile validates the pack against the marts, test-runs every metric, embeds pack items through the `embed` tier's alias (billable, needs `OPENAI_API_KEY`) and publishes the pack's Qdrant collections and `compiled.json`; see [packs/](packs/README.md#compiling-a-pack).
`ACTIVE_PACK` in `.env` names the pack the API serves.

### Screen questions

Every question is screened before any LLM call (DECISIONS §9): EN/VI rules and the local classifier `meta-llama/Llama-Prompt-Guard-2-86M`, which is gated and never stored in Git.
Accept its licence on Hugging Face, put an access token in `.env` as `HF_TOKEN`, then fetch and export it once into the `guard-models` volume:

```bash
docker compose run --rm guard-model
```

Without the classifier every question gets the blocked notice that screening is unavailable, in both modes; `/health` stays healthy and reports `screening: unavailable`.
`SCREEN_MODE=log` (default) records each question's verdict in `agent_logs.input_screening` and lets it continue; `enforce` also stops a blocked one with the `blocked` reply.
Measure the false-positive rate and recall per language before switching to `enforce`:

```bash
docker compose run --rm api python -m jobs.screen_eval --pack ecommerce_twin
```

### Ask a question

```bash
docker compose run --rm api python -m jobs.ask "Top 10 best-selling products in Q1 2024 compared with Q1 2025"
```

The agent extracts the question, resolves its periods, retrieves pack context, builds a QuerySpec, generates SQL through `sql-small` for a simple spec (one metric, at most one dimension, one period, no comparison or top N) and `sql-gen` otherwise, guards it, runs `EXPLAIN` and the query as the asking role's read-only ClickHouse user (`--role`, the pack's first role by default), repairs failing SQL up to three times (a retry after `sql-small` moves to `sql-gen`, the third through `sql-gen-hard`) and summarizes the rows in the question's language.
Each run sends billable requests to the LiteLLM aliases. Pass `--timezone <IANA name>` for relative periods (UTC by default) and `--inject-sql-fault` to watch a broken first query being repaired.
A question that names no measure or period, ranks by a word no convention defines, or uses a term that fits several metrics or columns prints a clarifying question with its options and exits with code 2, as does a question with a term or value that matches nothing; a question the role may not read exits with code 3 and the denial, before any SQL is generated, and is written to `agent_logs.audit`; a query that cannot be repaired exits with code 1 after printing the last SQL and error.

### Ask through the api

`POST /ask` answers one question as server-sent events, authenticated with a Keycloak access token.
For curl, the lab-only `finch-cli` client grants a token for a lab user whose password `jobs.set_lab_passwords` set (`KEYCLOAK_LAB_USER_PASSWORD` in `.env`):

```bash
TOKEN=$(curl -s -d grant_type=password -d client_id=finch-cli -d username=lab.analyst   --data-urlencode "password=$KEYCLOAK_LAB_USER_PASSWORD"   http://127.0.0.1:8080/realms/finch/protocol/openid-connect/token | python -c "import sys, json; print(json.load(sys.stdin)['access_token'])")
curl -N -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json"   -d '{"question":"Top 10 best-selling products in Q1 2024 compared with Q1 2025","timezone":"Asia/Ho_Chi_Minh"}'   http://127.0.0.1:8000/ask
```

The body is `{"question": ..., "conversation_id": null, "timezone": null}`, with the asker's IANA time zone (UTC when null).
A question without `conversation_id` starts a conversation; the response's `X-Conversation-Id` header names it, and passing that id with the next question makes it a follow-up that reads the previous turns. An id that is not one of the user's own conversations gets 404 before any work starts. Every question and answer is stored in `agent_logs.chat_messages`.
Each frame is `event: <name>` with JSON `data` carrying the run's `trace_id`, in the DECISIONS §6 order: `status` at the start and end of every graph node, then `sql` (the checked query, repeated for each repair), `result`, `chart_spec`, `summary` and `done` for an answer; `summary` and `done` alone for an out-of-scope or definition question; `result`, `chart_spec` and `done` without SQL when the question redraws the previous answer; `clarify` (a question with options whose labels can be sent as the next question) or `deny` and `done` when the question cannot be queried; `blocked` and `done` when screening stops the question, which is then not stored as a turn; `error` last when no SQL attempt produced a result.
A comment line keeps the connection open every 15 seconds. Disconnecting stops the run at its next node, stops its running ClickHouse query and logs the run as `cancelled`.

A missing, expired or otherwise invalid token gets 401. The request runs as one pack role: the one named by an `X-Active-Role` header, which the token must hold, or else the token's first role in `policies.yaml` order; a token without a pack role gets 403, and a role that may not read what the question needs gets a `deny` event (try `lab.marketing`).
Each user may ask `RATE_LIMIT_PER_MINUTE` questions per minute (10 by default); beyond it `/ask` answers 429 with `Retry-After` before any work starts.
With `conversation_id`, `edit_of_turn: k` asks the question in place of turn k and `retry_of_turn: k` asks turn k's question again, each under a new revision; the turns after k leave the conversation and its context.
`GET /conversations` (newest activity first, `limit` and `offset`), `GET /conversations/search?q=` (titles and the user's own questions, ignoring case and diacritics), `GET`/`PATCH`/`DELETE /conversations/{id}` (the current thread with each answer's events; title, pinned, group) and `GET`/`POST`/`PATCH`/`DELETE /conversation-groups` manage the signed-in user's conversations; another user's conversation or group, or a deleted one, is 404, and deleting only hides it from its owner.
`GET /me` returns the signed-in user, their pack and console roles and the active role; `GET /pack` names the active pack and its roles without a token.
Every run sends billable requests to the LiteLLM aliases, like `jobs.ask`.

### Score a pack's eval set

```bash
docker compose run --rm -v ./build/eval:/app/build/eval api python -m jobs.eval --pack ecommerce_twin --output-dir build/eval
```

Each active case in `packs/<pack>/eval.yaml` runs through the agent at temperature 0 with the eval set's `reference_date` as today, and is scored on the router's intent, extraction, retrieval and execution against its reference result; a case that expects a denial, a clarifying question or an out-of-scope reply scores that decision as its execution, and a `follow_up` or `chart_edit` case asks its `previous_question` first in the same conversation. Cases for branches of later phases are reported as not yet scored.
The run prints a Markdown report and, with `--output-dir`, also writes `<pack>-eval.md` and `<pack>-eval.json`; `--baseline <json>` compares the run with an earlier one, `--only <ids>` runs selected cases.
It exits with code 0 when the execution match rate reaches the pack threshold (80% by default) and no layer regressed, 1 otherwise, and 2 when the run cannot start or a reference query fails. Each run sends billable requests to the LiteLLM aliases.
The report shows the share of SQL first generated by `sql-small` and how often it escalated. `--tier <tier>=<alias>` runs a chat tier on another catalog alias, for example `--tier sql-small=anthropic-small`; the mapping of the tiers the run called and whether it regressed against `--baseline` are stored with the report in `agent_logs.eval_reports`. A run with `--only`, a `--threshold` below 80% or a reference error is stored without tier evidence.

### Map model tiers to aliases

Each tier calls its `MODEL_TIER_<TIER>` default from `.env`. An `admin` changes a chat tier on the console's Models page, backed by `GET /admin/models` and `PUT /admin/models/{tier}`: an alias is offered only when LiteLLM loaded it and is eligible when the latest eval report of the active pack that called the tier with it met the threshold and did not regress against its baseline; a tier no eval case reached, such as `sql-gen-hard` when nothing escalated, gets no evidence from that run. The mapping is stored in `data_meta.model_tiers`, read by the api at most 30 seconds later without a LiteLLM restart, and each change is recorded in `agent_logs.admin_actions`. `embed` changes only in `.env`, followed by a full reindex.

| Service | Host address | Health check |
| --- | --- | --- |
| web | [localhost:3000](http://localhost:3000) | page responds |
| api | [localhost:8000](http://localhost:8000/health) | `GET /health` |
| keycloak | [localhost:8080](http://localhost:8080) (realm `finch`) | management `/health/ready` |
| litellm | localhost:4000 | `/health/liveliness`, no OpenAI call |
| qdrant | localhost:6333 | `/readyz` |
| clickhouse | localhost:8123 (HTTP), localhost:9000 (native) | `GET /ping` |

`GET /health` returns `200` and `{"status":"ok"}` as a liveness probe; it calls no other service.
All ports bind to loopback. Open [API docs](http://localhost:8000/docs) for the API skeleton.
An earlier foundation ran a PostgreSQL `db` service with the `fitcher_pgdata` named volume. When upgrading a checkout that still has that container, start once with `docker compose up --build --wait --remove-orphans` so the old container stops and frees port 5432; this removes the container, not the volume. The volume is left untouched, and removing it with `docker volume rm fitcher_pgdata` is an explicit choice for its owner.

The `api` and `web` images apply available OS security updates during their builds and omit language package managers.
Refresh base images and OS security packages periodically, then recreate the services:

```bash
docker compose build --pull --no-cache
docker compose up -d --wait
```

`--no-cache` ensures the OS update layer is rerun. Dependency versions still come from the committed lockfiles; changes to base image tags and language runtimes need their own compatibility review.
ClickHouse, Qdrant, LiteLLM and Keycloak run upstream images pinned to exact tags in `compose.yaml`; `docker compose pull` changes nothing until a tag is updated deliberately.

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
npm --prefix apps/web run test
npm --prefix apps/web run build
npm --prefix apps/web run dev
```

Host and Docker services use the same ports; stop the Compose services before starting host servers.
`npm --prefix apps/web run test` runs the web unit tests (Vitest). Until each feature is wired to the api, the web app shows the active pack's sample data ([packs/](packs/README.md#sample-data-for-the-web-app)); set `ACTIVE_PACK` in the shell before `npm --prefix apps/web run dev` (Compose sets it for the `web` service). Open `http://localhost:3000` and sign in with a lab user through Keycloak (Continue with company account; the password is `KEYCLOAK_LAB_USER_PASSWORD` from `.env`), then ask one of the suggested questions: the answer streams from the api's `/ask` through the web server's `/api/ask` route, Stop ends the run on the api, and `lab.reviewer` and `lab.admin` also open the workspace console at `/console`. The web server runs the OIDC authorization code flow with PKCE against the `finch-web` client and keeps the tokens in a server-side session behind an httpOnly cookie, so a restart of the web server signs everyone out; sign-in needs Keycloak and the api running (`KEYCLOAK_ISSUER`, `KEYCLOAK_BACKCHANNEL_URL`, `APP_URL` and `API_URL` default to the host addresses, and Compose sets the container ones). In development, `/dev/components` shows the shared components of the design system in both languages and themes. After replacing `apps/web/app/styles/tokens.json` with a new export of the design tokens, run `npm --prefix apps/web run tokens` to regenerate `tokens.css`.
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

The Security workflow runs on PRs, integration/production pushes, manual dispatch and a weekly schedule. It audits locked npm/Python dependencies, scans Git history for secrets, rebuilds and scans the `api` and `web` images, and scans the four third-party service images by their pinned tags. Image jobs retain complete JSON reports and fail for High/Critical findings with a published fix; unfixed advisories remain visible for review. See [security policy](SECURITY.md) for triage and scanner limits. These jobs do not configure required status checks or branch protection automatically.

CodeRabbit is configured for `develop` and `main`, skips drafts, and reviews incremental updates without pausing after a fixed number of commits.
The CodeRabbit GitHub App must have access to this repository and a plan that supports the requested reviews.
Configuration alone does not install or authorize the App.
CodeRabbit reviews code only: agent instructions (`AGENTS.md`, `CLAUDE.md`, `.agents/`, `.claude/`) and documentation (`docs/`, Markdown files, PR and issue templates) are excluded from review.
PRs into `develop` are merged once every CI and Security check on the latest commit passes; the CodeRabbit review is not awaited, and each finding it has posted is verified, then fixed or answered with a reason.
CODEOWNERS and written rules do not themselves enforce branch protection; no branch protection is installed by this bootstrap.

Dependabot configuration is prepared for weekly GitHub Actions updates into `develop`.
Automatic version-update PRs are paused (`open-pull-requests-limit: 0`) because generated commit bodies conflict with the one-line commit policy.
Apply dependency changes on a normal work branch with compliant commits until an explicit bot policy is chosen.
The PR size labeler runs for branches within this repository; fork PRs do not receive a write token.

## Next steps

- Switch input screening to `SCREEN_MODE=enforce` once `jobs.screen_eval` shows no false positive and at least 90% recall in English and Vietnamese ([plan](docs/plans/phase-09b-input-screening.md)).
- Then Phase 9C (search on Qdrant), 9D (model routing across providers) and 9E (data sources from PostgreSQL, MySQL/MariaDB, MongoDB and files) before onboarding in Phase 10.
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
