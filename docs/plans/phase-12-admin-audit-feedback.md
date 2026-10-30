# Phase 12: Admin, audit and feedback loop

## Goal

Let operators observe and improve the system: an Admin UI over `agent_logs` (runs, traces, denials, LLM cost), and a job that turns disliked or failed runs into proposed examples for the Review UI, closing the loop back into eval.

## Scope

- Admin API endpoints and UI pages.
- `jobs/propose_examples.py` and its hand-off into the Phase 10 Review UI.

## Out of scope

- Alerting, dashboards outside the app, or any production monitoring stack.

## Prerequisites

- Phases 5, 6, 9 and 10: logs, audit, feedback, Review UI.

## Deliverables

```text
apps/api/app/api/admin.py           # runs, trace detail, audit, cost
apps/api/app/feedback/proposals.py  # build example proposals from runs
jobs/propose_examples.py
apps/web/app/(admin)/runs/
apps/web/app/(admin)/trace/[traceId]/
apps/web/app/(admin)/audit/
apps/web/app/(admin)/costs/
```

## Tasks

1. **Admin API (test first).** Paginated runs filtered by user, date range and status; trace detail combining `events`, `llm_calls`, `sql_runs`, `audit` and the query-log view; denied audit rows; cost by day, alias and model. Restricted to an `admin` role; queries use the logs read user.
2. **Admin UI.** Run list with filters, trace timeline, audit table, cost chart rendered through the existing ChartSpec adapter.
3. **Proposals (test first).** For each disliked or failed run, the job stores a proposal in `agent_logs.example_proposals` (90-day TTL, readable only by `pack_reviewer` and `admin`): question, final QuerySpec and SQL, error, feedback note and `trace_id`. Before storage, questions and notes pass a redaction step that masks emails, phone numbers and long digit sequences. Duplicates by normalized question are skipped.
4. **Review hand-off.** Proposals appear in the Review UI next to pack drafts. Approving one writes only fields the Phase 2 `examples.yaml` schema supports (question, SQL, `status`, `evidence: [{kind: trace, ref: <trace_id>}]`, `confidence`), after the reviewer edits the question and confirms it contains no personal data; feedback notes, errors and QuerySpecs never enter Git. Approval also offers adding an `eval.yaml` case for the question.
5. **Loop test.** Dislike a failing question, run the proposal job, approve and correct the example, compile, rerun eval; the case passes.

## Contracts

- Evidence kind `trace` added to the draft item schema.
- Admin endpoints under `/admin/*`, read-only.

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

## Risks and open questions

1. **Privacy of questions in proposals.** Users can type personal data into questions and notes regardless of the dataset. Default: automatic redaction plus mandatory reviewer confirmation before anything reaches Git; proposals never contain result rows and expire with the log TTL.
2. **Cost figures.** Depend on LiteLLM's cost table for the configured models; shown as estimates.
3. **Proposal storage table.** `example_proposals` adds a table to the seven in DECISIONS §10. Default: add it, and update DECISIONS §10 in the same PR with the owner's approval.

## Branch and PR split

- `feat/web/browse-runs-and-traces`: tasks 1-2.
- `feat/agent/propose-examples-from-feedback`: tasks 3-5.
