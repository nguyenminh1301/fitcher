# ecommerce_twin regenerated: drafted descriptions against the hand-written pack

Measured on 2026-11-05 for the Phase 10 regeneration experiment ([plan](../plans/phase-10-automated-onboarding.md), task 8).

## Setup

`packs/ecommerce_twin_regen/` is a copy of the hand-written `ecommerce_twin` pack in which every dataset description, column description, metric description and glossary definition was replaced with `Description to draft.` and those 36 items (3 datasets, 10 metrics, 23 glossary terms) were marked `status: draft`.
Ids, SQL, policies, relationships, examples and the eval set were left as reviewed, so the experiment measures the drafted text only.

```bash
docker compose run --rm jobs python -m jobs.profile --pack ecommerce_twin_regen
docker compose run --rm jobs python -m jobs.draft_pack --pack ecommerce_twin_regen --files datasets.yaml glossary.yaml metrics.yaml --allow-billable
# review in the console's Review section as a pack_reviewer, with ACTIVE_PACK=ecommerce_twin_regen
docker compose run --rm jobs python -m jobs.compile_pack --pack ecommerce_twin_regen
docker compose run --rm api python -m jobs.eval --pack ecommerce_twin_regen
docker compose run --rm api python -m jobs.eval --pack ecommerce_twin --baseline packs/ecommerce_twin/eval_baseline.json
```

The drafter worked from the profile only (no company documents): about 27 000 prompt tokens over three `sql-gen` calls.
It filled all 36 placeholders, added no new items and left no item with an `error` evidence.
`jobs.eval` accepts a baseline only from the same pack, so the regenerated run is compared case by case with a run of the hand-written pack made on the same day with the same model tiers (`fast` and `sql-small` on `openai-small`, `sql-gen` on `openai-medium`).

## Review

The reviewer signed in to the console as the lab `pack_reviewer`, read each drafted item against the hand-written meaning and the profile's real values, test-ran the metrics and approved all 36.
Three drafts were edited before approval because they lost a rule the pack relies on:

| Item | Draft | Approved |
| --- | --- | --- |
| `metrics.net_sales` | Total line amount for sales line items whose orders were not cancelled. | Total line amount of order lines in orders that were not cancelled. Returns are not deducted; see refund_total for refunded value. |
| `glossary.net_sales` | The total sales amount from order lines that were not cancelled. | The amount sold in orders that were not cancelled, before returns: returns are not deducted. |
| `glossary.best_selling` | Ranking by sales revenue or units sold rather than a single fixed measure. | Ranked by net sales, unless the question names another measure such as units sold; see the best_selling convention. |

The other 33 were approved as drafted; they are longer than the hand-written text but say the same thing.

## Result

| Layer | Hand-written | Regenerated |
| --- | --- | --- |
| Intent | 45/45 (100%) | 45/45 (100%) |
| Extraction | 25/28 scored (89%) | 25/28 scored (89%) |
| Retrieval | 33/33 scored (100%) | 33/33 scored (100%) |
| Execution match | 39/45 (87%) | 39/45 (87%) |

Every case has the same result in both runs: the same 39 pass and the same 6 fail (`refunds_last_quarter_vs_same_quarter_last_year`, `top_customers_by_net_sales_q2_2025`, `best_region_last_year_without_measure`, `marketing_asks_for_top_customers`, `net_sales_by_category_follow_up` and `monthly_orders_next_year_follow_up`).
The nine definition questions, which answer from the regenerated descriptions through `metadata_qa`, all pass.
Both runs meet the 80% pack threshold, and the hand-written run shows no regression against `packs/ecommerce_twin/eval_baseline.json`.

The rule for "not significantly lower" (execution match within 5 percentage points of the hand-written pack) holds with a difference of 0 points.

## Notes

- The Review page shows a dataset's description but not its drafted column descriptions; those were checked in `datasets.yaml` before approving.
- Drafting rewrote each dataset's column list as block mappings instead of one-line flow mappings; the values are unchanged.
