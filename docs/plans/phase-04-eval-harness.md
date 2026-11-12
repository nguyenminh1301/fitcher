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
  runner.py                         # sequential runs with a per-case timeout, reference results
  report.py                         # Markdown and JSON rendering, baseline diff
jobs/eval.py                        # CLI: --pack <name> [--only <ids>] [--baseline <file>]
packs/ecommerce_twin/eval.yaml      # >= 30 cases
docs/eval/ecommerce_twin-baseline.md
packs/ecommerce_twin/eval_baseline.json
```

## Tasks

1. **Case format (test first).** Each case: `id`, `question`, `category` (two_period_compare, top_n, string_filter, monthly_trend, ambiguous, unauthorized, out_of_scope), expected labels (`intent`, `periods`, `top_n`, `rank_by`, `dataset`, `columns`) and either `expected_sql` (run to obtain the reference result) or `expected_rows`, never both. The eval file sets one `reference_date` used as "today" for every case. Optional `active_from_phase` keeps categories whose feature is not built yet out of the score.
2. **Result comparison (test first).** Compare result sets, never SQL strings, and match columns by value rather than by name or position: each expected key column (dimension or time) and each expected measure maps to a distinct actual column of the same kind whose values match, so renamed or reordered columns still match; extra actual columns (such as a percentage change) are allowed. Numeric tolerance `|a - b| <= max(rel * max(|a|, |b|), abs)` with configurable `rel = 1e-6` and `abs = 1e-9`, so zero-valued measures compare safely; row order significant only when the case ranks (top N, ordered trend). Tests: reordered columns, float noise, zero-valued measures, missing row, extra row, rank-order difference, extra columns.
3. **Scorers.** Extraction: exact match on periods, top_n, rank_by. Retrieval: recall of expected dataset and columns in the retrieved candidates. Execution: comparison result. Intent scoring activates with the router.
4. **Runner.** Runs the graph in-process for the pack named by `--pack`, which overrides `ACTIVE_PACK` for that run (retrieval, catalog and roles all come from that pack), and runs cases sequentially with a fixed reference date, temperature 0 where the model allows, and a per-case timeout; one failing case never aborts the run. The LLM client sends `temperature: 0` for eval runs and the LiteLLM proxy drops the parameter for models that reject it (`drop_params`).
5. **Reports.** Markdown summary per layer and category, per-case table with failure reason, JSON for machines. `--baseline` prints deltas and exits nonzero on regression beyond tolerance.
6. **Eval set.** Write at least 30 cases covering every DECISIONS §12 category; reference results are produced by running `expected_sql` against the marts.
7. **Baseline.** Run once, commit `docs/eval/ecommerce_twin-baseline.md` and `eval_baseline.json`.

## Contracts

- `eval.yaml` schema extends the Phase 2 eval schema.
- Exit codes: 0 no regression and the pack threshold met, 1 regression or execution match below the threshold, 2 runner error (including a failing `expected_sql`).
- Pack threshold: execution match >= 80% of active scored cases (DECISIONS §14).

## Verification

```bash
uv run --project apps/api pytest -c apps/api/pyproject.toml
docker compose run --rm -v ./build/eval:/app/build/eval api python -m jobs.eval --pack ecommerce_twin --baseline packs/ecommerce_twin/eval_baseline.json --output-dir build/eval
```

Eval runs are billable and explicit; CI runs only the unit tests with fake clients.

## Definition of done

| DoD item | Proof |
|---|---|
| A baseline report exists | Committed baseline Markdown and JSON |
| Later phases rerun eval without regression | Rule in [plans/README.md](README.md); each PR attaches its report and baseline diff |

## Risks and open questions

1. **Inactive categories.** MASTER_PLAN asks Phase 4 to cover all §12 categories, but deny, clarify and out-of-scope need Phases 6 and 8. Settled: label them now with `active_from_phase`, report them as "not yet scored".
2. **Nondeterminism.** LLM outputs vary between runs. Settled: a regression is a layer whose pass count, over the cases scored in both runs, drops by more than one case; the owner can raise this to multiple runs per case later.
3. **Baseline location.** Settled: tracked under `packs/<pack>/eval_baseline.json` with a human-readable copy under `docs/eval/`.
4. **Pack threshold.** DECISIONS §11 enables a pack only above a threshold. Settled: execution match >= 80% on active cases; below it `eval.py` exits 1.

## Branch and PR split

- `feat/agent/score-eval-cases-per-layer`: tasks 1-3 (case format, comparison, scorers).
- `feat/agent/run-eval-from-cli`: tasks 4-5 (runner, temperature, reports, CLI).
- `feat/pack/record-ecommerce-eval-baseline`: tasks 6-7.
