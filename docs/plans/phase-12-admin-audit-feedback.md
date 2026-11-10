# Phase 12: Admin, audit and feedback loop

## Goal

Let operators observe and improve the system: console sections over `agent_logs` (runs, traces, denials, LLM cost, feedback, eval reports), user role management through Keycloak, and a job that turns disliked or failed runs into proposed examples for the Review UI, closing the loop back into eval (DECISIONS §15).

## Scope

- Admin API endpoints and UI pages.
- `jobs/propose_examples.py` and its hand-off into the Phase 10 Review UI.
- Feedback, Evaluation and Users sections of the console.

## Out of scope

- Alerting, dashboards outside the app, or any production monitoring stack.

## Prerequisites

- Phases 5, 6, 9 and 10: logs, audit, feedback, Review UI.
- Phase 9B: `input_screening`; Phase 9D: `llm_calls.tier` and the provider of each alias.

## Deliverables

The web files listed here are created in Phase 6B on sample data; this phase adds the api side and changes them only to wire it (see Web wiring).

```text
apps/api/app/api/admin.py           # runs, trace detail, audit, cost
apps/api/app/feedback/proposals.py  # build example proposals from runs
jobs/propose_examples.py
apps/api/app/api/feedback_review.py # feedback list, propose one example
apps/api/app/api/evaluation.py     # eval reports, start an eval run
apps/api/app/api/users.py          # realm users, role changes, disable/enable
apps/api/app/auth/keycloak_admin.py # Admin API client for the service account
apps/web/app/(console)/runs/ trace/[traceId]/ audit/ costs/
apps/web/app/(console)/feedback/ evaluation/ users/
infra/keycloak/realm-finch.json    # fitcher-admin-api confidential client
infra/clickhouse/                  # agent_logs.admin_actions, fresh-volume init plus apply path
```

## Tasks

1. **Admin API (test first).** Paginated runs filtered by user, date range and status; trace detail combining `events`, `llm_calls`, `sql_runs`, `audit` and the query-log view; denied audit rows and input-screening verdicts (`input_screening`, filtered by verdict and source); cost by day, alias, model, tier and provider; `GET /admin/conversations?user=` and `GET /admin/conversations/{id}` list and read any user's conversations with their messages and trace ids, including conversations their owner deleted, which are marked as deleted. Restricted to an `admin` role; queries use the logs read user.
2. **Admin UI.** The run list, trace timeline, audit table and cost chart are built in Phase 6B; this task wires them to the Admin API of task 1 (see Web wiring).
3. **Proposals (test first).** Eligible runs are disliked or failed `data_query` runs that produced both a QuerySpec and SQL; clarify, deny and policy-rejected runs are excluded. For each, the job stores a proposal in `agent_logs.example_proposals` (90-day TTL, readable only by `pack_reviewer` and `admin`): proposal `id`, `pack`, question, final QuerySpec and SQL, nullable error (absent for disliked successful runs), nullable feedback note and `trace_id`. Before storage, every user-derived value passes a redaction step that masks emails, phone numbers and long digit sequences: question, feedback note, QuerySpec filter values, SQL string literals and echoed error text. Duplicates by `(pack, normalized question)` are skipped.
4. **Review hand-off.** Proposals appear in the Review UI next to pack drafts. Approving one writes only fields the Phase 2 `examples.yaml` schema supports (`id`, kept from the proposal, question, SQL, `status`, `evidence: [{kind: trace, ref: <trace_id>}]`, `confidence`), with `status: approved`, after the reviewer edits the question, replaces every masked SQL literal with a valid non-personal value, test-runs the SQL through the Review API and confirms that neither contains personal data; feedback notes, errors and the run's QuerySpec never enter Git. A reviewer may add a reviewed spec to the example (DECISIONS §6 step 7), built only from pack metrics, columns and values. Approval also offers adding an `eval.yaml` case for the question.
5. **Loop test.** Dislike a failing question, run the proposal job, approve and correct the example, compile, rerun eval; the case passes.
6. **Feedback section (test first).** `GET /admin/feedback` (`pack_reviewer`) lists likes and dislikes with question, note, run status and trace, newest first, filtered by rating and date; `POST /admin/feedback/{trace_id}/proposal` runs the task 3 code for that one run and returns the proposal or the reason it is not eligible.
7. **Evaluation section (test first).** `GET /admin/eval-reports` and `GET /admin/eval-reports/{id}` read `eval_reports` for the active pack (per-layer rates, threshold result, categories, failed cases, the baseline comparison). `POST /admin/eval-runs` (`admin` only) starts the active pack's eval set in a background thread inside `api` with the same runner and report code as `jobs/eval.py`, refuses a second run for the pack while one is running (409), and stores the report when done; the page labels the action as using paid AI and asks for confirmation. Tests use the fake LLM and runner.
8. **Users section (test first).** A `fitcher-admin-api` confidential client in the realm with a service account holding only `realm-management` `view-users` and `manage-users`; its secret comes from `.env`. `GET /admin/users` lists users with their pack roles and enabled flag; `PUT /admin/users/{id}/roles` sets the user's pack roles (only roles defined by the active pack's policies); `POST /admin/users/{id}/disable` and `/enable`. The api refuses changes to the acting admin's own account, never creates or deletes users or sets credentials, and writes each change to `agent_logs.admin_actions` (`ts, actor, action, target, old_value, new_value`; Phase 9D created the table, and `target` holds the user id). Tests use a fake Keycloak Admin API and cover each refusal.

## Contracts

- Evidence kind `trace` added to the draft item schema.
- Admin endpoints under `/admin/*`: read-only except starting an eval run, proposing an example from one run and the Users changes.

## Verification

```bash
uv run --project apps/api pytest -c apps/api/pyproject.toml
npm --prefix apps/web run typecheck
npm --prefix apps/web run build
docker compose run --rm api python -m jobs.propose_examples --pack ecommerce_twin
docker compose run --rm api python -m jobs.eval --pack ecommerce_twin --baseline packs/ecommerce_twin/eval_baseline.json
```

## Definition of done

| DoD item | Proof |
|---|---|
| Disliked question -> proposal -> approved -> passes in the next eval | Loop test transcript with trace id, review action and eval result |
| An admin changes a user's role and the user's next token carries it | Users test plus a manual check recorded in the PR |
| Each console section shows only to its roles | Navigation and endpoint tests per role |
| An admin reads a conversation its owner deleted; the owner no longer sees it | Endpoint test across the owner and admin views |

## Risks and open questions

1. **Privacy of questions in proposals.** Users can type personal data into questions and notes regardless of the dataset. Default: automatic redaction plus mandatory reviewer confirmation before anything reaches Git; proposals never contain result rows and expire with the log TTL.
2. **Cost figures.** Depend on LiteLLM's cost table for the configured models; shown as estimates.
3. **Proposal storage table.** Settled: `example_proposals` is listed in DECISIONS §10 and was created with the other log tables in Phase 5.
4. **Eval runs inside api.** A run takes minutes and is billable. Default: one run per pack at a time, started only by `admin`, with no automatic schedule.
5. **Role change latency.** Keycloak puts roles in the access token. Default: a change applies at the next token refresh (the realm's access token lifespan); the Users page says so.

## Web wiring

The Phase 6B web app runs every feature on the active pack's sample data until its backend exists ([phase-06b](phase-06b-web-app-on-sample-data.md)). `apps/web/lib/api/client.ts` defines each feature's methods, `lib/api/mock/` holds the sample implementation, `lib/api/http/` the real one, and `lib/api/sources.ts` chooses between them. This phase wires:

| Feature | Mock to retire | Real endpoint | Contract | Done when |
|---|---|---|---|---|
| `runs` | `console.json` runs and traces | the runs and trace detail endpoints of task 1 | `FitcherApi.runs` | `sources.runs` is `http`, its Sample data badge is gone, the http client test passes and its provisional types are deleted |
| `audit` | `console.json` audit rows | the denied audit and input-screening endpoints of task 1 | `FitcherApi.audit` | `sources.audit` is `http`, its Sample data badge is gone, the http client test passes and its provisional types are deleted |
| `costs` | `console.json` cost rows | the cost endpoint of task 1 | `FitcherApi.costs` | `sources.costs` is `http`, its Sample data badge is gone, the http client test passes and its provisional types are deleted |
| `feedbackReview` | `console.json` feedback rows | `GET /admin/feedback` and the proposal endpoint (task 6) | `FitcherApi.feedbackReview` | `sources.feedbackReview` is `http`, its Sample data badge is gone, the http client test passes and its provisional types are deleted |
| `evaluation` | `console.json` eval reports and a simulated run | `GET /admin/eval-reports`, `GET /admin/eval-reports/{id}`, `POST /admin/eval-runs` (task 7) | `FitcherApi.evaluation` | `sources.evaluation` is `http`, its Sample data badge is gone, the http client test passes and its provisional types are deleted |
| `users` | `console.json` users with local role changes | `GET /admin/users`, `PUT /admin/users/{id}/roles`, disable and enable (task 8) | `FitcherApi.users` | `sources.users` is `http`, its Sample data badge is gone, the http client test passes and its provisional types are deleted |

## Branch and PR split

- `feat/web/browse-runs-and-traces`: tasks 1-2.
- `feat/agent/propose-examples-from-feedback`: tasks 3-5.
- `feat/web/review-feedback-and-eval-reports`: tasks 6-7.
- `feat/api/manage-user-roles`: task 8.
