# Jobs

Command-line jobs for loading data, profiling, compiling packs, drafting packs and running evals.
They share the `api` image, which copies this directory to `/app/jobs`, and run manually or from CI; reusable engine logic stays in `apps/api`.

| Job | Command | Notes |
| --- | --- | --- |
| `smoke_llm.py` | `docker compose exec -T api python -m jobs.smoke_llm` | One billable request to the `fast` alias; prints only the reply length |

See [DECISIONS §3](../docs/DECISIONS.md#3-docker-compose). The data loader arrives in [Phase 1](../docs/plans/phase-01-data-and-marts.md).
