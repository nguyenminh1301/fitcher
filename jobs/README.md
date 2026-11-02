# Jobs

Command-line jobs for loading data, profiling, compiling packs, drafting packs and running evals.
They share the `api` image, which copies this directory to `/app/jobs`, and run manually or from CI; reusable engine logic stays in `apps/api`.

| Job | Command | Notes |
| --- | --- | --- |
| `smoke_llm.py` | `docker compose exec -T api python -m jobs.smoke_llm` | One billable request to the `fast` alias; prints only the reply length |
| `load_data.py` | `docker compose run --rm jobs python -m jobs.load_data --source <name>` | Loads the source described by `sources/<name>.yaml` into ClickHouse `raw`; publishes all tables or none |

| `refresh_data.py` | `docker compose run --rm jobs python -m jobs.refresh_data --source <name>` | Loads the source, then runs `dbt build --select +tag:<dbt_tag>`; records the generation in `data_meta.refresh_log` |
| `ask.py` | `docker compose run --rm api python -m jobs.ask "<question>"` | Runs the `data_query` agent as the read-only ClickHouse user and prints the SQL attempts, result table, warnings and summary; billable LiteLLM calls; writes the run, node events and SQL attempts to `agent_logs` under the printed trace id; `--timezone`, `--reference-date`, `--inject-sql-fault` |
| `compile_pack.py` | `docker compose run --rm jobs python -m jobs.compile_pack --pack <name>` | Validates the pack, test-runs its metrics, applies its access policies to ClickHouse and publishes a new generation of its search indices; billable embeddings unless `--skip-index`; `--check-search "<query>"` searches the live pack |
| `apply_log_schema.py` | `docker compose run --rm jobs python -m jobs.apply_log_schema` | Creates the `agent_logs` database and tables on a volume created before they existed; the fresh-volume `initdb` runs the same file, and a rerun changes nothing |
| `eval.py` | `docker compose run --rm -v ./build/eval:/app/build/eval api python -m jobs.eval --pack <name> --output-dir build/eval` | Scores the pack's approved eval cases per layer at temperature 0 and prints a Markdown report; writes `<pack>-eval.md` and `<pack>-eval.json` with `--output-dir`; `--only <ids>`, `--baseline <json>`, `--timeout`, `--threshold`; billable LiteLLM calls; exits 0, 1 on a regression or below the threshold, 2 on a setup or reference-query error |

A refresh records `started`, then `completed` only when the load and every dbt model and test succeed, or `failed` otherwise.
Readers trust a source only when its latest `refresh_log` row is the same `completed` generation before and after their operation.
A per-source lock table rejects concurrent refreshes; if a crashed refresh left it behind and no refresh is running, drop it with `DROP TABLE data_meta.refresh_lock_<source>`.

On a Linux host, create `build/eval` before an eval run and make it writable by the container user (uid 10001), or omit `--output-dir` and keep the printed report.

Jobs that need ClickHouse admin access run in the `jobs` Compose service (profile `jobs`); shared helpers live in `lib/` and tests in `tests/`.

See [DECISIONS §3](../docs/DECISIONS.md#3-docker-compose) and the [Phase 1 plan](../docs/plans/phase-01-data-and-marts.md).
