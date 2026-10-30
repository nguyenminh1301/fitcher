# Jobs

Command-line jobs for loading data, profiling, compiling packs, drafting packs and running evals.
They share the `api` image and run manually or from CI; reusable engine logic stays in `apps/api`.

See [DECISIONS §3](../docs/DECISIONS.md#3-docker-compose). The first job, the data loader, arrives in [Phase 1](../docs/plans/phase-01-data-and-marts.md).
