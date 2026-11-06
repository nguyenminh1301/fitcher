# iowa_liquor: a second industry onboarded with no engine change

Measured on 2026-11-06 for Phase 11 ([plan](../plans/phase-11-industry-neutrality.md)): Iowa Liquor Sales 2025, state-regulated spirits wholesale, served from a PostgreSQL source and onboarded only through the Phase 10 pipeline.

## Neutrality evidence

| Check | Result |
| --- | --- |
| `git diff --stat 3040704..HEAD -- apps/api apps/web` (3040704 is `develop` before this phase) | prints nothing |
| `python scripts/check_pack_isolation.py` with both packs | passes, 76 pack names checked |
| Data path | `infra/sources/iowa_liquor/` (fetch and seed script) and `jobs/sources/iowa_liquor.yaml` only; no new loader in `jobs/` |
| `ecommerce_twin` | not rerun: since its 2026-11-05 run (39/45, no regression against its baseline, [report](ecommerce_twin_regen-report.md)) `apps/api` changed only the `pypdf` pin, and this phase changed nothing under `apps/` |

## How the pack was built

```bash
python infra/sources/iowa_liquor/fetch.py                     # 2 490 620 invoice lines
docker compose --profile sources exec postgres-fixture sh /seed/iowa_liquor/seed.sh
docker compose run --rm jobs python -m jobs.refresh_data --source iowa_liquor
docker compose run --rm jobs python -m jobs.profile --pack iowa_liquor --tables liquor_sales
docker compose run --rm jobs python -m jobs.draft_pack --pack iowa_liquor --files datasets.yaml metrics.yaml glossary.yaml examples.yaml --allow-billable
# review in the console's Review section as a pack_reviewer, with ACTIVE_PACK=iowa_liquor
docker compose run --rm jobs python -m jobs.compile_pack --pack iowa_liquor
docker compose run --rm api python -m jobs.eval --pack iowa_liquor
```

The drafter worked from the mart profile only (no documents), about 5 000 prompt tokens over four `sql-gen` calls.
It produced the dataset with its 19 columns, 13 metrics, 15 glossary terms and 8 examples; every drafted metric and example passed its test-run.
Policies (`analyst`, `polk_county_manager` with a Polk County row filter, `vendor_partner` without the state's cost and margin), the business profile and the eval set were written by hand, as a company would.

## Review

All drafted items were approved in the console after these corrections:

| Item | Correction |
| --- | --- |
| `metrics.average_state_margin_rate`, `average_retail_per_bottle`, `average_retail_per_liter` | Drafted as the average of per-line ratios; changed to a ratio of sums, for example `sum(state_margin) / nullIf(sum(sale_dollars), 0)` |
| `examples.category_margin_rate` | Same ratio-of-sums correction in its SQL |
| `glossary.vodka`, `rum`, `bourbon` | Added the categories the draft missed (imported flavored vodka; aged dark and gold rum; single barrel and bottled in bond bourbon) |
| `datasets.liquor_sales` | `store_city`, `store_name`, `vendor_name` and `item_description` made indexable so their values can be filtered |
| `business_profile` | Convention: "best-selling" ranks by `total_sales_dollars` |

Targets, indexable columns and conventions cannot be edited on the Review page, so those were edited in the YAML, as a reviewer does in the pull request.

A first three-case eval then showed one more review gap: the pack had no term for "vendor", and the `store` and `item` terms pointed at a metric and two columns at once, so "top vendors" was answered with a clarifying question.
The glossary was corrected to one meaning per term (measure terms point at their metric only; `store` at `store_name`, `item` at `item_description`) and gained `vendor`, `category`, `city` and `state_bottle_cost` terms and the plain Vietnamese alias "doanh thu".

## Result

| Layer | Passed |
| --- | --- |
| Intent | 34/35 (97%) |
| Extraction | 23/24 scored (96%) |
| Retrieval | 24/25 scored (96%) |
| Execution match | 29/35 (83%) |

The pack meets the 80% threshold.
Every category passes at least once: two-period comparisons 4/4, top N 5/5, string filters 4/5, monthly trends 2/4, ambiguous 2/3, unauthorized 2/3, out of scope 2/2, follow-ups 2/3, chart edits 2/2 and definitions 4/4.

The six failing cases, kept as they are to spend no further paid calls once the threshold was met:

| Case | Why |
| --- | --- |
| `vodka_bottles_2025`, `monthly_bourbon_sales_2025` | The answer's measure column was not recognised by the scorer; the bourbon run also did not retrieve `category_name` |
| `monthly_margin_rate_2025` | No result |
| `average_without_measure` | Answered instead of asking which measure |
| `vendor_partner_asks_for_margin` | Routed out of scope instead of being denied; no data was shown |
| `top_counties_q4_follow_up` | The follow-up kept the whole year instead of Q4 |

## Notes

- Screening flagged six product names as possible injections while compiling (for example two "REDEMPTION" rye whiskeys scored as blocks); column values are listed and still indexed, as DECISIONS §9 requires.
- The first eval attempt failed on an exhausted OpenAI credit balance (HTTP 429 on 30 of 35 cases) and is not counted.
