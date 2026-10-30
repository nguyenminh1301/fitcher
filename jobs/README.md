# Jobs

Command-line jobs for loading data, profiling, compiling packs, drafting packs and running evals.
They share the `api` image, which copies this directory to `/app/jobs`, and run manually or from CI; reusable engine logic stays in `apps/api`.

| Job | Command | Notes |
| --- | --- | --- |
| `smoke_llm.py` | `docker compose exec -T api python -m jobs.smoke_llm` | One billable request to the `fast` alias; prints only the reply length |
| `load_data.py` | `docker compose run --rm jobs python -m jobs.load_data --source <name>` | Loads the source described by `sources/<name>.yaml` into ClickHouse `raw`; publishes all tables or none |

Jobs that need ClickHouse admin access run in the `jobs` Compose service (profile `jobs`); shared helpers live in `lib/` and tests in `tests/`.

See [DECISIONS §3](../docs/DECISIONS.md#3-docker-compose) and the [Phase 1 plan](../docs/plans/phase-01-data-and-marts.md).
