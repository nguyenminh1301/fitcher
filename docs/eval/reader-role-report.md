# Eval after packs moved to one reader role

fitcher became a personal app, so a Domain Pack no longer declares roles: the loader grants every approved dataset to one `reader` role (DECISIONS §9).
The sample packs lost their `policies.yaml` and the three role-refusal cases each (`ecommerce_twin`: `marketing_asks_for_*`; `iowa_liquor`: `vendor_partner_asks_for_*`).
Every other case still runs, now as `reader`, which reads the same columns the packs' `analyst` role did.

Both packs were recompiled and evaluated on the development stack with OpenAI on every tier (`sql-small` `gpt-5.4-mini`, `sql-gen` `gpt-5.4`, `sql-gen-hard` `gpt-5.5`, embeddings `text-embedding-3-large`):

```bash
docker compose run --rm -T jobs python -m jobs.compile_pack --pack ecommerce_twin
docker compose run --rm -T jobs python -m jobs.compile_pack --pack iowa_liquor
docker compose run --rm -T -v ./build/eval:/app/build/eval api python -m jobs.eval --pack ecommerce_twin --baseline packs/ecommerce_twin/eval_baseline.json --output-dir build/eval
docker compose run --rm -T -v ./build/eval:/app/build/eval api python -m jobs.eval --pack iowa_liquor --baseline <the previous iowa_liquor run> --output-dir build/eval
```

## Result

| Pack | Execution match | Threshold | Baseline (common cases) |
| --- | --- | --- | --- |
| `ecommerce_twin` | 38/42 (90%) | met | no layer regressed: execution 20 → 21 of 22, extraction 20 → 20, retrieval 22 → 22 |
| `iowa_liquor` | 31/32 (97%) | met | no layer regressed: execution 27 → 31 of 32, retrieval 24 → 25, extraction 23 → 23 |

The `iowa_liquor` baseline is the previous run of the same 35-case set, which has no tracked baseline file.

## Cases that differ from the previous run

| Pack | Case | Now | Cause |
| --- | --- | --- | --- |
| `ecommerce_twin` | `best_region_last_year_without_measure` | fail | `gpt-5.4-mini` replied with JSON that does not match the extraction schema, so the question was rejected before it could be clarified; not related to access |
| `ecommerce_twin` | `net_sales_by_category_follow_up` | fail | the follow-up produced no result; the run reads the same columns as before |
| `iowa_liquor` | `agave_tequila_liters_des_moines_2025`, `monthly_bourbon_sales_2025`, `average_without_measure`, `top_vendors_by_bottles_follow_up` | pass | failed in the previous run |

No case changed because of access: the reader role reads every column the `analyst` role read, and no remaining case asks for data that role could not read.
