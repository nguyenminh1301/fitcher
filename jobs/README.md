# Jobs

Command-line jobs for loading data, profiling, compiling packs, drafting packs and running evals.
They share the `api` image, which copies this directory to `/app/jobs`, and run manually or from CI; reusable engine logic stays in `apps/api`.

| Job | Command | Notes |
| --- | --- | --- |
| `smoke_llm.py` | `docker compose exec -T api python -m jobs.smoke_llm [--tier <tier>]` | One tiny request per model mapped to a tier (billable for a hosted provider), checking structured output, and one local or provider embedding; prints only pass or fail |
| `load_data.py` | `docker compose run --rm jobs python -m jobs.load_data --source <name>` | Loads the Hugging Face source described by `sources/<name>.yaml` into ClickHouse `raw`; publishes all tables or none |
| `sync_sources.py` | `docker compose run --rm jobs python -m jobs.sync_sources --source <name>` | Copies any other source into `raw.<source>__<table>` (all tables or none) or, in live mode, defines `src_<source>`, and counts each table against the manifest; `--mode copy` or `--mode live` overrides the manifest |
| `refresh_data.py` | `docker compose run --rm jobs python -m jobs.refresh_data --source <name>` | Loads or syncs the source, then runs `dbt build --select +tag:<dbt_tag>` over it; records the generation in `data_meta.refresh_log`; `--mode` as for `sync_sources` |
| `ask.py` | `docker compose run --rm api python -m jobs.ask "<question>"` | Runs the `data_query` agent as one pack role (`--role`, the pack's first role by default) and its ClickHouse user and prints the SQL attempts, result table, warnings and summary; billable model calls through the gateway; writes the run, node events and SQL attempts to `agent_logs` under the printed trace id; `--timezone`, `--reference-date`, `--inject-sql-fault` |
| `compile_pack.py` | `docker compose run --rm jobs python -m jobs.compile_pack --pack <name>` | Validates the pack, test-runs its metrics, applies its access policies to ClickHouse and publishes a new generation of its search indices; billable embeddings unless `--skip-index`; `--check-search "<query>"` searches the live pack |
| `profile.py` | `docker compose run --rm jobs python -m jobs.profile --pack <name> [--tables a,b]` | Profiles the pack's marts (its `datasets.yaml` ids, or `--tables` for a new pack) into `build/packs/<pack>/profile.json`: row counts, column types and distinct counts, date ranges, top values of low-cardinality strings, sample rows and join-key candidates; no LLM call |
| `ingest_docs.py` | `docker compose run --rm jobs python -m jobs.ingest_docs --pack <name> --folder <dir>` | Uploads every document listed in `<dir>/manifest.yaml` (`default_allowed_roles`, `documents: [{file, allowed_roles}]`) through the same code as the console's Documents page; billable embeddings; skips duplicates and exits 1 if any document failed |
| `draft_pack.py` | `docker compose run --rm jobs python -m jobs.draft_pack --pack <name> --allow-billable` | Drafts `datasets.yaml`, `glossary.yaml`, `metrics.yaml` and `examples.yaml` (`--files` picks some) from `profile.json` and the pack's `kb_docs` chunks (`--document <id>` for one document) with one billable `sql-gen` call per file; drafts never replace approved items; without `--allow-billable` it prints the prompt size and exits 2 |
| `propose_examples.py` | `docker compose run --rm jobs python -m jobs.propose_examples --pack <name> [--days 90]` | Turns every disliked or failed `data_query` run of the pack in the last `--days` days that produced a QuerySpec and SQL into one row of `agent_logs.example_proposals`, after masking emails, phone numbers and long digit runs; skips clarified, denied, rejected and blocked runs and questions already proposed, and prints the count of each; a `pack_reviewer` approves or deletes each proposal in the console's Review section; no LLM call |
| `seed_dev_accounts.py` | `docker compose run --rm jobs python -m jobs.seed_dev_accounts` | Creates or resets the development accounts of `infra/dev/accounts.yaml` with the password `DEV_ACCOUNT_PASSWORD` and puts the instance in team mode; never prints the password |
| `migrate.py` | `docker compose run --rm jobs python -m jobs.migrate` | Applies the pending numbered schema changes to ClickHouse (`infra/clickhouse/changes`, recorded in `data_meta.schema_changes`) and to the app state (`<FITCHER_DATA_DIR>/app.db`, recorded in `schema_changes`); a second run applies nothing, a volume created before the runner is recorded as up to date without changing a row, and a store written by a newer version is refused. `jobs.apply_log_schema` remains as an alias |
| `fetch_guard_model.py` | `docker compose run --rm guard-model` | Downloads the gated prompt-injection classifier (`meta-llama/Llama-Prompt-Guard-2-86M`) with `HF_TOKEN`, exports it to ONNX in its own PyTorch image (`fetch_guard_model.Dockerfile`), checks the export against PyTorch and known inputs and writes `model.onnx`, `tokenizer.json` and `version.json` to the `guard-models` volume; never prints the token; `--revision` |
| `screen_eval.py` | `docker compose run --rm api python -m jobs.screen_eval --pack <name>` | Screens the benign set (the pack's eval questions and sample questions plus `apps/api/tests/screening/benign.yaml`) and the attack set (`attacks.yaml`) with the local classifier and prints the false-positive rate, recall, latency and misclassified items per language, and whether the DECISIONS §9 gate for `SCREEN_MODE=enforce` holds; no LLM call; `--json <file>` |
| `eval.py` | `docker compose run --rm -v ./build/eval:/app/build/eval api python -m jobs.eval --pack <name> --output-dir build/eval` | Scores the pack's approved eval cases per layer at temperature 0 and prints a Markdown report; writes `<pack>-eval.md` and `<pack>-eval.json` with `--output-dir`; `--only <ids>`, `--baseline <json>`, `--timeout`, `--threshold`; billable model calls through the gateway; exits 0, 1 on a regression or below the threshold, 2 on a setup or reference-query error |

A refresh records `started`, then `completed` only when the load and every dbt model and test succeed, or `failed` otherwise.
Readers trust a source only when its latest `refresh_log` row is the same `completed` generation before and after their operation.
A per-source lock table rejects concurrent refreshes; if a crashed refresh left it behind and no refresh is running, drop it with `DROP TABLE data_meta.refresh_lock_<source>`.

On a Linux host, create `build/eval` before an eval run and make it writable by the container user (uid 10001), or omit `--output-dir` and keep the printed report.

Jobs that need ClickHouse admin access run in the `jobs` Compose service (profile `jobs`); shared helpers live in `lib/` and tests in `tests/`.

## Data sources

A pack's data is declared in a source manifest, `sources/<name>.yaml`, validated by [`sources/source.schema.json`](sources/source.schema.json) and `lib/source_manifest.py` ([DECISIONS §4](../docs/DECISIONS.md#data-sources)).
Every source is reached through ClickHouse, so the agent still writes ClickHouse SQL over marts under the RBAC of DECISIONS §9.

| `kind` | Tables declare | Copy reads with | Live mode defines |
| --- | --- | --- | --- |
| `huggingface` | `file`, `format: parquet`, `expected_rows` | `jobs.load_data` (copy only) | - |
| `postgres` | `name`, optional `source` table | `postgresql()` | `src_<source>` with the `PostgreSQL` database engine |
| `mysql` (MySQL or MariaDB) | `name`, optional `source` table | `mysql()` | `src_<source>` with the `MySQL` database engine |
| `mongodb` | `name`, optional `source` collection, `columns` with ClickHouse types | `mongodb()` | one `MongoDB` table engine per collection |
| `files` | `name`, `path` (object key in the bucket), `format` (`csv` or `parquet`), optional `columns` | `s3()` | one `S3` table engine per file |

`expected_rows` is optional for every kind but `huggingface`; when present, a different count fails the sync and publishes nothing.
Manifests that share a `dbt_tag` feed one set of dbt models and must declare the same table names; the models read whichever of them was synced last.

### Adding a source

1. Create a read-only user for it on the source system.
2. Add `sources/<name>.yaml` with `kind`, `mode`, `connection_env: <PREFIX>` and its tables.
3. Add a `<name>` block to [`infra/clickhouse/config.d/sources.xml`](../infra/clickhouse/config.d/sources.xml) that reads `<PREFIX>_HOST`, `_PORT`, `_DATABASE`, `_USER` and `_PASSWORD` from the environment (an S3 store takes one `url`, which `compose.yaml` builds from the host, port and bucket), pass those variables to the `clickhouse` service in `compose.yaml`, set them in `.env` and restart ClickHouse.
4. Write the staging models of its `dbt_tag` with `{{ source_table('<table>') }}`, casting every column explicitly, since each engine maps source types differently.
5. Run `jobs.refresh_data --source <name>`.

Only ClickHouse holds the credentials: the named collection reads them from its environment, engine definitions and sync queries name the collection, and `system.named_collections` hides them.
Only the `source_loader` user ([`infra/clickhouse/users.d/sources.xml`](../infra/clickhouse/users.d/sources.xml)) may use the collections; the `jobs` service connects as it with `CLICKHOUSE_SOURCES_PASSWORD` and never receives a source credential.

### Choosing a mode

- **`copy`** (default): each sync loads `raw.<source>__<table>__loading`, counts it and exchanges it into `raw.<source>__<table>`, so a failed sync leaves the previous copy in place. Questions never load the source; data is as fresh as the last sync. Run syncs by hand, from CI or from the host's scheduler; there is no scheduler service.
- **`live`**: dbt builds the marts as views over `src_<source>`, so every question runs on the source system. Use it for small tables that must be fresh. The mart views run with the privileges of their definer, the dbt user, so an agent role is granted the mart and never `src_*` or `raw`.

Column grants, row policies and aggregate-only views behave the same on live marts as on copied data: `apps/api/tests/test_sources_live.py` checks them on each live kind and on a copy, so no policy has to force copy mode.
A MongoDB collection is read live only when it is flat; a nested collection is copied with its documents' top-level fields and flattened in dbt.
After a PostgreSQL source restarts, ClickHouse's `PostgreSQL` engine fails the first query on each pooled connection with `broken_connection` and reconnects for the next one, so a live question can fail once and succeed when asked again; the MySQL, MongoDB and S3 engines reconnect without an error.

### Fixture sources

The `sources` Compose profile starts lab-only PostgreSQL, MySQL, MongoDB and S3-compatible (SeaweedFS) fixtures seeded with the synthetic widget dataset of [`infra/sources/fixtures`](../infra/sources/fixtures) (40 widgets, 3,000 sales and 300 refunds), each with a read-only user.
The manifests `fixture_postgres`, `fixture_mysql`, `fixture_mongodb` and `fixture_files` feed the `fixture_widgets` marts `widget_sales` and `widget_refunds`, whose columns cover the minimal test pack.

```bash
docker compose --profile sources up -d --wait
docker compose run --rm jobs python -m jobs.sync_sources --source fixture_postgres
docker compose run --rm jobs python -m jobs.refresh_data --source fixture_mongodb --mode live
```

The live tests sync every fixture in both modes from the host and compare the marts:

```bash
SOURCES_LIVE_TEST=1 CLICKHOUSE_HOST=localhost uv run --project apps/api pytest -c apps/api/pyproject.toml apps/api/tests/test_sources_live.py
```

See [DECISIONS §3](../docs/DECISIONS.md#3-docker-compose), the [Phase 1 plan](../docs/plans/phase-01-data-and-marts.md) and the [Phase 9E plan](../docs/plans/phase-09e-data-sources.md).
