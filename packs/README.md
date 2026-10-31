# Domain Packs

Each company is described by a Domain Pack in `packs/<company>/`: eight YAML files validated by the JSON Schemas in [`_schema/`](_schema/).
Git is the source of truth for packs; the engine under `apps/` contains no pack-specific names.

| File | Contents |
| --- | --- |
| `business_profile.yaml` | Name (equal to the directory name), industry, currency, fiscal year start month and default conventions such as "best-selling = net sales"; the user's time zone and answer language come from each request |
| `datasets.yaml` | One entry per `marts` table: description, grain, primary time column, `allowed_roles` and columns with type, role (dimension, measure, time) and whether their top values are indexed |
| `glossary.yaml` | Terms with Vietnamese and English aliases, each targeting metrics, columns or column values |
| `metrics.yaml` | One aggregate `sql_expr` over one dataset, with grain, unit and owner |
| `relationships.yaml` | The only join paths generated SQL may use |
| `examples.yaml` | Questions with canonical SQL for few-shot prompts |
| `policies.yaml` | Roles with the datasets, columns and optional row filter each may read |
| `eval.yaml` | Labelled questions covering every required category, with the expected intent, outcome, extraction, retrieval and reference SQL |

Every list item carries `status` (`draft` or `approved`), `evidence` (`[{kind, ref}]`, kind one of `manual`, `profile`, `doc`, `error`, `trace`) and `confidence`; only approved items are compiled.
Shared definitions live in `_schema/common.schema.json`.
Pack files use YAML 1.2 scalars: dates stay strings and only `true`/`false` are booleans, so keys such as `on` keep their name.

Loading a pack (`app.packs.loader.load_pack`) validates every file against its schema, then checks references: unique ids, known metrics, datasets, columns and roles, time columns, indexable string columns, dataset `allowed_roles` equal to the roles `policies.yaml` grants, and, given a warehouse catalog, that every dataset table and column exists.
All problems are reported together as `<file>: <item path>: <message>`.
The API tests load every pack here against the column lists of the dbt mart schemas.

[`ecommerce_twin/`](ecommerce_twin/) describes the `sales_lines`, `returns_fact` and `sessions_daily` marts of the e-commerce lab dataset.

## Compiling a pack

```bash
docker compose run --rm jobs python -m jobs.compile_pack --pack ecommerce_twin
docker compose run --rm jobs python -m jobs.compile_pack --pack ecommerce_twin --check-search "doanh thu"
```

The compiler (`app.packs.compiler`) loads the pack with the ClickHouse `marts` catalog, keeps approved items, parses every metric's `sql_expr` as one expression and runs it once read-only with a time limit, and reads each dataset's row count and time-column range.
It then writes generation `v<N+1>` of the six OpenSearch indices `<pack>_<index>_v<N>` (`glossary_terms`, `metrics`, `datasets` with one document per column, `column_values` with the top `COLUMN_VALUES_TOP_K` values of indexable columns, `examples`, and `kb_docs`, which stays empty until runtime documents arrive in Phase 10).
Every document carries the roles that `policies.yaml` grants its dataset or column.
Text fields fold case and diacritics; all indices except `column_values` carry an `EMBEDDING_DIMENSIONS`-sized vector from the `embed` alias for the `hybrid_search` pipeline (BM25 and kNN, min-max normalized), and `column_values` adds fuzzy and trigram matching for misspelled values.
Once every index is filled, one request moves the six `<pack>_<index>` aliases, `compiled.json` (the approved pack, generation and date coverage) is written to the `compiled-packs` volume, and older generations are deleted; a failure before the alias move deletes the partial generation and leaves the live aliases untouched.

Indexing sends billable embedding requests; `--skip-index` stops after the metric test-run without calling LiteLLM or OpenSearch.
`--check-search` searches the live aliases as every role of the pack, or as each `--role` given.

See [DECISIONS §5](../docs/DECISIONS.md#5-domain-pack) and the [Phase 2 plan](../docs/plans/phase-02-domain-pack-and-compiler.md).
