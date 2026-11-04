# Phase 11: Industry neutrality proof

## Goal

Show that the engine is industry- and source-neutral: serve a second dataset from a different industry out of a PostgreSQL database, connect it through a Phase 9E source manifest, onboard it using only the Phase 10 pipeline, write its eval set, and reach the eval threshold with zero changed lines in `apps/api` and `apps/web`.

## Scope

- Choose the second dataset (Iowa Liquor Sales or `SDataPro/maycee-retail-dataset`) and place it in the fixture PostgreSQL of the `sources` profile, as a company's own database would hold it.
- Connect it with a source manifest (`kind: postgres`), in copy mode unless the RBAC test of Phase 9E allows live mode for its policies.
- dbt marts for it, a pack produced by profile -> draft -> review -> compile, and its `eval.yaml`.
- Evidence that engine code did not change.

## Out of scope

- Any engine change. If one is required, the phase stops, the gap is recorded, and the fix lands as a separate engine PR first; the proof is then rerun from a clean state.

## Prerequisites

- Phases 9E and 10 complete; eval threshold agreed (Phase 4 open question 4).

## Deliverables

```text
infra/sources/<second_pack>/             # seed script placing the dataset in PostgreSQL (outside the engine)
jobs/sources/<second_pack>.yaml          # kind: postgres
dbt/models/<second_pack>/staging/ marts/
packs/<second_pack>/                # all eight files, approved through review
docs/eval/<second_pack>-report.md
```

## Tasks

1. **Choose the dataset.** Compare licence, size and shape. Iowa Liquor Sales is real, one wide table and large, so its seed script places a bounded period in PostgreSQL; Maycee needs its licence and table layout confirmed. Record the choice in DECISIONS §4.
2. **Connect.** Seed the dataset into PostgreSQL outside the engine, then declare it in a source manifest only; `jobs/sync_sources.py` (copy) or the live engine definition (Phase 9E) is reused unchanged, and dbt builds only the models tagged with the new pack.
3. **Marts.** dbt models in a separate folder; 1-3 wide marts.
4. **Onboard.** `profile.py` -> `ingest_docs.py` (if documents exist) -> `draft_pack.py` -> Review UI -> `compile_pack.py`.
5. **Eval set.** At least 30 cases covering every DECISIONS §12 category, with reference SQL.
6. **Neutrality evidence.** `git diff --stat <phase base>..HEAD -- apps/api apps/web` prints nothing; `check_pack_isolation.py` passes with both packs.
7. **Run.** Set `ACTIVE_PACK` to the new pack, run eval, record the report.

## Contracts

- None new. Any needed contract change is an engine gap (see Out of scope).

## Verification

```bash
docker compose --profile sources up --wait
docker compose run --rm api python -m jobs.sync_sources --source <second_pack>   # copy mode; the manifest dbt_tag selects only this pack's models
docker compose run --rm api python -m jobs.compile_pack --pack <second_pack>
docker compose run --rm api python -m jobs.eval --pack <second_pack>
docker compose run --rm api python -m jobs.eval --pack ecommerce_twin --baseline packs/ecommerce_twin/eval_baseline.json   # --pack overrides ACTIVE_PACK (Phase 4)
git diff --stat <phase base>..HEAD -- apps/api apps/web
python scripts/check_pack_isolation.py
```

## Definition of done

| DoD item | Proof |
|---|---|
| New pack runs with 0 changed lines in `apps/api` and `apps/web` | Empty `git diff --stat` output |
| The data arrives through a source manifest only | No new loader in `jobs/`; the manifest and seed script are the only data-path files |
| Reaches the eval threshold | Eval report in the PR |
| The first pack does not regress | `ecommerce_twin` eval report and baseline diff in the PR |

## Risks and open questions

1. **Dataset choice.** Default: Iowa Liquor Sales, bounded to recent full years, because it is real data from a clearly different domain.
2. **Active pack switching.** DECISIONS allows one active pack per run. Default: switch with `ACTIVE_PACK` and restart `api`; both packs coexist because the search collections and aliases are pack-scoped (`<pack>_<index>`, Phase 9C), and compiling one pack never touches the other's collections.
3. **dbt selection by pack.** Default: one dbt project with a folder and tag per pack, built with `--select tag:<pack>`.

## Web wiring

No feature is wired in this phase. The new pack ships its own `sample_data/` (Phase 6B), the web app runs on it with `ACTIVE_PACK` switched, and `git diff --stat <phase base>..HEAD -- apps/web` prints nothing.

## Branch and PR split

- `feat/db/load-second-industry-dataset`: tasks 1-3.
- `feat/pack/onboard-second-industry-pack`: tasks 4-7.
