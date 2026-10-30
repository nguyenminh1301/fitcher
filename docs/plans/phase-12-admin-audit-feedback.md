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
apps/web/app/(admin)/runs/ trace/[traceId]/ audit/ costs/
```

## Tasks

1. **Admin API (test first).** Paginated runs filtered by user, date range and status; trace detail combining `events`, `llm_calls`, `sql_runs`, `audit` and the query-log view; denied audit rows; cost by day, alias and model. Restricted to an `admin` role; queries use the logs read user.
2. **Admin UI.** Run list with filters, trace timeline, audit table, cost chart rendered through the existing ChartSpec adapter.
3. **Proposals (test first).** For each disliked or failed run: the question, the final QuerySpec and SQL, the error or feedback note. The job writes a draft `examples.yaml` item with `status: draft`, `evidence: [{kind: trace, ref: <trace_id>}]` and low confidence; duplicates by normalized question are skipped.
4. **Review hand-off.** Proposals appear in the Review UI like any draft; approving one also offers adding an `eval.yaml` case for the question.
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

1. **Privacy of questions in proposals.** Questions may contain personal data. Default: the lab dataset is synthetic; proposals keep only the question and SQL, never result rows.
2. **Cost figures.** Depend on LiteLLM's cost table for the configured models; shown as estimates.

## Branch and PR split

- `feat/web/browse-runs-and-traces`: tasks 1-2.
- `feat/agent/propose-examples-from-feedback`: tasks 3-5.
