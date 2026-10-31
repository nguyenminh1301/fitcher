# Phase 2: Hand-written Domain Pack and compiler

## Goal

Define the Domain Pack format, write the complete `packs/ecommerce_twin/` pack by hand, and compile it: validate it, test-run every metric, and index it into the six versioned OpenSearch indices.

## Scope

- JSON Schemas for the eight pack files (DECISIONS §5).
- The hand-written e-commerce pack.
- A pack loader and compiler in engine code, exposed through `jobs/compile_pack.py`.
- OpenSearch index mappings, aliases and hybrid search pipeline.

## Out of scope

- Generating ClickHouse roles, grants and row policies from `policies.yaml` (Phase 6). This phase validates `policies.yaml` only.
- `kb_docs` content from company documents (Phase 10); the index is created empty.
- Drafted items; every hand-written item is `status: approved`.

## Prerequisites

- Phase 1 marts in `marts` with real data.
- Phase 0 OpenSearch and the LiteLLM `embed` alias.

## Deliverables

```text
packs/
  _schema/                          # one JSON Schema (draft 2020-12) per pack file
    business_profile.schema.json ... eval.schema.json
  ecommerce_twin/
    business_profile.yaml datasets.yaml glossary.yaml metrics.yaml
    relationships.yaml examples.yaml policies.yaml eval.yaml
apps/api/app/packs/
  models.py                         # Pydantic models mirroring the schemas
  loader.py                         # load + schema + cross-reference validation
  compiler.py                       # metric test-run, index build
  search_indices.py                 # mappings, aliases, pipeline definitions
jobs/compile_pack.py                # CLI: --pack <name> [--skip-index]
```

## Tasks

1. **Schemas and models (test first).** Each schema requires `id` where items are referenced, plus `status`, `evidence`, `confidence` on draftable items. One shared evidence definition `[{kind, ref}]` with `kind` in `manual`, `profile`, `doc`, `error`, `trace` serves every later phase. Tests: a valid minimal pack loads; each schema rejects a missing required field, an unknown key and a bad enum with a message naming file, item path and field.
2. **Cross-reference validation.** Metrics reference existing datasets; glossary targets exist; relationship columns exist in both datasets; examples and eval reference known metrics; dataset columns exist in ClickHouse `system.columns`. Tests use a fake catalog.
3. **Hand-written pack.** Fill all eight files for the Phase 1 marts. Glossary terms carry Vietnamese and English aliases (for example "doanh thu" / "net sales" / "revenue"). `business_profile.yaml` sets industry, currency, fiscal start month and the "best-selling = by net sales" convention; time zone and answer language come from each request (DECISIONS §6). `eval.yaml` starts with a handful of seed cases; Phase 4 grows it.
4. **Metric test-run.** For every approved metric, parse `sql_expr` with sqlglot (clickhouse dialect) as a single expression, then run `SELECT <expr> FROM marts.<dataset> LIMIT 1` as the admin user with a short `max_execution_time`. Failures abort the compile with the metric id and ClickHouse error.
5. **OpenSearch indices.** The six logical indices (`glossary_terms`, `metrics`, `datasets`, `column_values`, `examples`, `kb_docs`) are pack-scoped: physical names are `<pack>_<index>_v<N>` and aliases are `<pack>_<index>`, so packs never overwrite each other and retrieval reads the aliases of `ACTIVE_PACK`. The first compile creates `_v1`. Text fields use an analyzer with lowercase and ASCII folding so Vietnamese diacritics match; a `knn_vector` field sized from the configured embedding dimensions; `allowed_roles` as a keyword on every document. Register a hybrid search pipeline (BM25 + kNN, normalized and combined).
6. **column_values.** For string columns marked indexable in `datasets.yaml`, read top-K distinct values with counts and index each value with its column and dataset. Values also get an n-gram or fuzzy-matchable field so misspellings match.
7. **Embeddings.** Batch embeddings through the `embed` alias. Unit tests use a fake embedding client; the real run is the explicit compile command.
8. **Compile CLI.** Order: load -> validate -> test-run metrics -> build indices -> swap aliases. Each compile writes a new generation `v<N+1>` of all six indices for that pack; after every index is populated, one `_aliases` request moves all six aliases atomically, and only then is the previous generation deleted. A failed compile deletes its partial generation and leaves the live aliases untouched; a test covers a failure midway through indexing. Until Phase 10 adds runtime documents, each generation's `kb_docs` is empty; from then on the compiler fills it from the document registry (DECISIONS §5).

## Contracts

- Pack file shapes are the JSON Schemas; Pydantic models are generated from or kept identical to them by a test.
- Index document shapes: `{id, type, text_fields..., embedding, allowed_roles, pack}`.
- Configuration: `ACTIVE_PACK`, `OPENSEARCH_URL`, `EMBEDDING_DIMENSIONS`, `COLUMN_VALUES_TOP_K`.

## Verification

```bash
uv run --project apps/api pytest -c apps/api/pyproject.toml
docker compose run --rm jobs python -m jobs.compile_pack --pack ecommerce_twin
python -m jobs.compile_pack --pack <copy> --packs-dir <dir> --skip-index      # a copy with a broken schema or sql_expr must fail
```

The compile runs in the `jobs` service, the only one holding the ClickHouse admin credentials (Phase 1).

Search checks are scripted in `jobs/compile_pack.py --check-search "<query>"` or a test against a live OpenSearch marked `integration`.

## Definition of done

| DoD item | Proof |
|---|---|
| The pack compiles | Compile summary: items per index, metrics tested |
| A broken pack is rejected clearly | Fixtures with an invalid schema and a failing `sql_expr`; expected messages asserted in tests |
| "doanh thu" / "net sales" finds the right metric | Hybrid search result shows `net_sales` first |
| A misspelled product name finds the right value | Search result in `column_values` |

## Risks and open questions

1. **Where engine code lives.** Default: pack loading/compiling is engine code in `apps/api/app/packs/` because the runtime needs the same models; `jobs/compile_pack.py` is a thin CLI. This keeps pack-specific names out of `apps/`.
2. **Compiled artifact for runtime.** The runtime needs dataset date coverage and column metadata. Default: the compiler writes `build/packs/<pack>/compiled.json` (ignored) and indexes the same data; the api loads it at startup.
3. **Top-K size and indexable columns.** Product names may be high-cardinality. Default: K = 10,000 per column, columns opt in through `datasets.yaml`.
4. **Hybrid search availability.** Requires the OpenSearch neural search pipeline features of the pinned version; verify at phase start.
5. **Glossary language coverage.** Who writes Vietnamese aliases for the seed pack; default: the owner reviews the drafted list in the PR.

## Branch and PR split

- `feat/pack/define-domain-pack-schema`: tasks 1-3.
- `feat/pack/compile-pack-into-search-indices`: tasks 4-8.
