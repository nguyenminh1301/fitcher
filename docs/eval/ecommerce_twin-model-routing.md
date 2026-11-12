# ecommerce_twin model routing: sql-small against sql-gen

Measured on 2026-11-04 with the pack eval (DECISIONS §2 Model tiers, §6 step 9, Phase 9D), both runs compared with `packs/ecommerce_twin/eval_baseline.json`:

```bash
docker compose run --rm api python -m jobs.eval --pack ecommerce_twin --baseline packs/ecommerce_twin/eval_baseline.json
docker compose run --rm api python -m jobs.eval --pack ecommerce_twin --tier sql-small=openai-medium --baseline packs/ecommerce_twin/eval_baseline.json
```

"Routing on" uses the `.env` defaults, where `sql-small` is `openai-small` (the model behind `fast`) and `sql-gen` is `openai-medium`.
"Routing off" maps `sql-small` to `openai-medium` too, so every SQL generation runs on the model all SQL used before this phase.
Both runs keep `fast` on `openai-small`, `sql-gen-hard` on `openai-large` and `embed` on `openai-embed`.
Costs are the LiteLLM estimates in `agent_logs.llm_calls`, summed over the traces of each run's cases and grouped by the new `tier` column.

| | Routing on | Routing off |
| --- | --- | --- |
| Execution match | 40/45 (89%) | 41/45 (91%) |
| Regression against the baseline | none | none |
| Cases that generated SQL | 24 | 24 |
| First generation on `sql-small` | 11 (46%) | 11 (46%) |
| Escalated after `sql-small` | 0 | 0 |
| `sql-small` calls cost | $0.0154 | $0.0540 |
| All SQL generation cost | $0.1083 | $0.1470 |
| Whole run cost | $0.1802 | $0.2184 |
| Cost per answered question | $0.00450 | $0.00533 |

Routing cut the cost of the simple questions' SQL by 71%, all SQL generation by 26% and the cost per answered question by 16%.
Every simple question routed to `sql-small` passed on its first attempt except `monthly_orders_next_year_follow_up`, which fails the same way with routing off and before this phase (its follow-up period resolves to one month).
The one case that passed only with routing off, `marketing_asks_for_top_customers`, generates no SQL: the run asked a clarifying question instead of denying, a difference in the `fast` tier's extraction between two runs at temperature 0, not in the SQL tiers.

Both reports are stored in `agent_logs.eval_reports` with their tier mapping, so the routing-on run makes `openai-small` eligible for `sql-small` and the routing-off run makes `openai-medium` eligible for it on the console's Models page.
Only OpenAI aliases were measured: the Anthropic, Gemini and local aliases stay ineligible until a run with their key and `--tier` passes.
