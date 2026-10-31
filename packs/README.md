# Domain Packs

Each company is described by a Domain Pack in `packs/<company>/`: eight YAML files validated by the JSON Schemas in [`_schema/`](_schema/).
Git is the source of truth for packs; the engine under `apps/` contains no pack-specific names.

| File | Contents |
| --- | --- |
| `business_profile.yaml` | Name (equal to the directory name), industry, currency, time zone, fiscal year start month, answer language and default conventions such as "best-selling = net sales" |
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

See [DECISIONS §5](../docs/DECISIONS.md#5-domain-pack) and the [Phase 2 plan](../docs/plans/phase-02-domain-pack-and-compiler.md); compiling packs into OpenSearch arrives with the pack compiler.
