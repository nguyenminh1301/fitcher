# Phase 4: Eval harness

## Goal

Measure answer quality per layer before adding features: `eval.py --pack ecommerce_twin` runs the pack's eval set through the agent and reports extraction accuracy, retrieval recall and execution result match, establishing a baseline that later phases must not regress.

## Scope

- Eval runner, scorers and Markdown/JSON reports.
- Growing `packs/ecommerce_twin/eval.yaml` to at least 30 labelled questions.
- A tracked baseline and a regression comparison.

## Out of scope

- Storing reports in `agent_logs` (added in Phase 5 once the tables exist).
- Router, clarify and deny scoring as active metrics; those cases are labelled now and activated in Phases 6 and 8.

## Prerequisites

- Phase 3 graph callable as a library function returning the final state.

## Deliverables

```text
apps/api/app/eval/
  cases.py                          # load eval.yaml into typed cases
  scorers.py                        # per-layer scoring
  compare.py                        # result-set comparison
  report.py                         # Markdown and JSON rendering, baseline diff
jobs/eval.py                        # CLI: --pack <name> [--only <ids>] [--baseline <file>]
packs/ecommerce_twin/eval.yaml      # >= 30 cases
docs/eval/ecommerce_twin-baseline.md
packs/ecommerce_twin/eval_baseline.json
```

## Tasks

1. **Case format (test first).** Each case: `id`, `question`, `category` (two_period_compare, top_n, string_filter, monthly_trend, ambiguous, unauthorized, out_of_scope), expected labels (`intent`, `periods`, `top_n`, `rank_by`, `dataset`, `columns`) and either `expected_sql` (run to obtain the reference result) or `expected_rows`. Optional `active_from_phase` keeps categories whose feature is not built yet out of the score.
2. **Result comparison (test first).** Compare result sets, never SQL strings: column match by role and order of measures, numeric tolerance (relative 1e-6, configurable), row order significant only when the case ranks (top N, ordered trend). Tests: reordered columns, float noise, missing row, extra row, rank-order difference.
3. **Scorers.** Extraction: exact match on periods, top_n, rank_by. Retrieval: recall of expected dataset and columns in the retrieved candidates. Execution: comparison result. Intent scoring activates with the router.
4. **Runner.** Runs cases sequentially with a fixed reference date, temperature 0 where the model allows, and a per-case timeout; one failing case never aborts the run.
5. **Reports.** Markdown summary per layer and category, per-case table with failure reason, JSON for machines. `--baseline` prints deltas and exits nonzero on regression beyond tolerance.
6. **Eval set.** Write at least 30 cases covering every DECISIONS §12 category; reference results are produced by running `expected_sql` against the marts.
7. **Baseline.** Run once, commit `docs/eval/ecommerce_twin-baseline.md` and `eval_baseline.json`.

## Contracts

- `eval.yaml` schema extends the Phase 2 eval schema.
- Exit codes: 0 pass or no regression, 1 regression, 2 runner error.

## Verification

```bash
uv run --project apps/api pytest -c apps/api/pyproject.toml
docker compose run --rm api python -m jobs.eval --pack ecommerce_twin --baseline packs/ecommerce_twin/eval_baseline.json
```

Eval runs are billable and explicit; CI runs only the unit tests with fake clients.

## Definition of done

| DoD item | Proof |
|---|---|
| A baseline report exists | Committed baseline Markdown and JSON |
| Later phases rerun eval without regression | Rule in [plans/README.md](README.md); each PR attaches its report and baseline diff |

## Risks and open questions

1. **Inactive categories.** MASTER_PLAN asks Phase 4 to cover all §12 categories, but deny, clarify and out-of-scope need Phases 6 and 8. Default: label them now with `active_from_phase`, report them as "not yet scored".
2. **Nondeterminism.** LLM outputs vary between runs. Default: a regression is a drop larger than one case per layer; the owner can raise this to multiple runs per case later.
3. **Baseline location.** Default: tracked under `packs/<pack>/eval_baseline.json` with a human-readable copy under `docs/eval/`.
4. **Pack threshold.** DECISIONS §11 enables a pack only above a threshold. Default proposal: execution match >= 80% on active cases; the owner sets the final number.

## Branch and PR split

- `feat/agent/score-eval-cases-per-layer`: tasks 1-5.
- `feat/pack/record-ecommerce-eval-baseline`: tasks 6-7.
