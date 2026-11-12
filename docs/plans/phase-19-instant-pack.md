# Phase 19: Instant pack from a connected source

## Goal

Make the first question possible minutes after a source is connected, with no dbt model and no YAML written by hand: the application builds marts from the chosen tables, drafts a pack, approves it as unreviewed and compiles it. Review and eval remain available and become optional (DECISIONS §4, §5, §11).

## Scope

- Marts generated from selected source tables, including one wide view per fact table.
- Pack files generated from the profile, the source's keys and the drafter.
- The `reviewed` flag and its display.
- The setup flow from "source connected" to "ask a question".
- A measurement of answer quality against the hand-written packs.

## Out of scope

- Replacing dbt for the development datasets.
- Generating an eval set; an instance without `eval.yaml` shows no eval result.
- More than one active pack per instance.
- Automatic re-drafting when a source's schema changes; this phase detects and reports the change.

## Prerequisites

- Phase 17 (sources), Phase 14 (models), Phase 10 code (profiler, drafter, review), Phase 15 (roles).

## Deliverables

```text
apps/api/app/onboarding/marts.py     # mart views from selected tables; wide view per fact table
apps/api/app/onboarding/relationships.py # foreign keys from the source, candidates from the profile
apps/api/app/onboarding/instant.py   # the pipeline: marts, profile, pack files, draft, approve, compile
apps/api/app/api/instant.py          # start, progress, result
packs/_schema/                       # reviewed flag on drafter-generated items
apps/web/app/setup/                  # progress screen after the Data step
docs/eval/instant-pack-report.md     # instant packs against the hand-written ones
```

## Tasks

1. **Baseline measurement first.** Before writing the generator, build by hand what it would produce for the two development sources (the seven raw e-commerce tables and the single Iowa table), compile those packs and run the existing eval sets. Record execution match next to the hand-written packs in `docs/eval/instant-pack-report.md`. This number decides how much of task 3 is needed and is the reference for the definition of done.
2. **Mart views (test first).** Each selected table becomes `marts.<source>__<table>`, a view with `SQL SECURITY DEFINER` over `src_<source>` or `raw`, as the live marts of Phase 9E. Columns keep their names; unsupported types are cast to strings; nothing is renamed by an LLM.
3. **Wide views (test first).** The agent is built for wide marts with few joins. For each fact table (a table with outgoing foreign keys that no selected table references), generate a second view that joins its dimension tables along single-column foreign keys, one level deep, prefixing joined columns with the dimension's name. The fact's own mart and the wide view are both datasets; the wide one is preferred in `datasets.yaml`. A wide view over tables read live is flagged as slow and the setup proposes copying them.
4. **Relationships (test first).** Foreign keys read from the source catalog become approved join paths. Join-key candidates from the profiler stay `draft` and are never used until a person approves them: the LLM may not invent joins.
5. **Pack files (test first).** Deterministic first: `datasets.yaml` from the profile (numeric columns as measures, date and time columns as time, low-cardinality strings as dimensions, keys hidden), a `business_profile.yaml` with neutral defaults, `policies.yaml` with one role that reads every dataset. Then the drafter fills descriptions, metrics, glossary terms with English and Vietnamese aliases, and examples, as in Phase 10.
6. **Unreviewed items.** Add `reviewed: false` to the pack schema for generated items. The instant pipeline writes its items as `approved` and `reviewed: false`; the compiler uses them; the Review page lists them first, and an answer that used an unreviewed metric says so under the SQL. Confirming an item in Review sets `reviewed: true`.
7. **Pipeline and API (test first).** `POST /pack/instant` runs marts, profile, files, draft, compile as one job with progress events and one result. The draft is a paid call: the request must carry an explicit confirmation and the setup shows the estimated prompt size first. A failure leaves the previous pack live and reports the step that failed.
8. **Setup flow.** After the Data step: the confirmation, a progress screen naming each step, then the chat with three suggested questions taken from the drafted examples. When no model is configured the flow stops before the draft and says what is missing.
9. **Schema drift.** On each sync or daily for live tables, compare the source's columns with the pack's datasets and show added, removed and retyped columns on the Sources page with a "rebuild pack" action.
10. **Eval not a gate.** Remove the check that keeps a pack disabled below the eval threshold; the Evaluation page keeps reporting it.
11. **Measure again.** Run the generator on the two development sources, run the eval sets and complete the report with per-layer results and the failing categories.

## Contracts

- `POST /pack/instant` with `{source_id, tables, confirm_billable}`, `GET /pack/instant/{job}` (progress and result).
- Pack schema: optional `reviewed: boolean` beside `status`, `evidence` and `confidence`.
- Mart names `marts.<source>__<table>` and `marts.<source>__<table>__wide`.

## Verification

```bash
uv sync --project apps/api --frozen
uv run --project apps/api pytest -c apps/api/pyproject.toml
python scripts/check_pack_isolation.py
npm --prefix apps/web run typecheck && npm --prefix apps/web run test && npm --prefix apps/web run build
docker compose run --rm jobs python -m jobs.eval --pack ecommerce_twin   # hand-written pack must not regress
```

Billable drafts and evals for the report run once each.

## Definition of done

- On a fresh instance, connecting the development PostgreSQL source and confirming the draft leads to an answered question with a chart, without a terminal.
- The instant packs' execution match is recorded for both development sources. The phase passes when each reaches at least the value measured in task 1; the gap to the hand-written packs is stated in the report, not hidden.
- The hand-written packs' evals do not regress.
- No pack table, column or metric name appears in `apps/`.

## Risks and open questions

- Answer quality without hand-made marts is the largest product risk of the roadmap. Default: ship with the unreviewed labels and the measured gap; improve from the Review and Feedback pages.
- Sources without declared foreign keys get no joins. Default: single-table datasets only, and the Sources page explains that approving a candidate relationship enables joins.
- A source with hundreds of tables. Default: the user selects tables; the setup preselects none above 20 and warns above 50.

## Branch and PR split

`chore/pack/measure-generated-packs` (task 1), `feat/db/build-marts-from-selected-tables` (2 to 4), `feat/pack/generate-pack-from-a-source` (5 to 7, 10), `feat/web/ask-right-after-connecting` (8, 9), `chore/pack/report-generated-pack-quality` (11).
