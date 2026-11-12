# Phase 20: Search in ClickHouse and optional documents

## Goal

Remove the last extra process. Pack search (glossary, metrics, datasets, column values, examples, documents) moves from Qdrant into ClickHouse, provided retrieval recall does not fall; company documents become a choice made in setup (DECISIONS §2, §5, §14, §15).

## Scope

- A ClickHouse search index behind the interface of `app/search/client.py`.
- The measurement that decides the switch.
- Removal of Qdrant, or the recorded decision to keep it.
- The documents switch and the setup's Documents step.

## Out of scope

- A new ranking method: dense plus BM25 fused with RRF, as today.
- A vector index for very large collections; exact search is used and its cost measured.
- OCR and new document formats.

## Prerequisites

- Phase 14 (local embeddings), Phase 16 (Qdrant runs inside the container and is the fallback).

## Deliverables

```text
apps/api/app/search/clickhouse_index.py  # create, write, switch and query collections in ClickHouse
apps/api/app/search/engine.py            # the interface both engines implement
infra/clickhouse/changes/                # search database, tables and the search user
docs/eval/search-engine-report.md        # recall and latency of both engines
apps/web/app/setup/                      # Documents step
```

## Tasks

1. **Interface.** Extract what the compiler and the retrieve node need from `app/search/client.py` into `engine.py` (create a generation, upsert points, switch live, hybrid query with a role filter, copy `kb_docs` chunks, delete by document) and make the Qdrant client implement it without behaviour change.
2. **ClickHouse index (test first).** One table per collection and generation in a `search` database: id, payload JSON, `allowed_roles`, dense vector as `Array(Float32)`, sparse terms and weights as parallel arrays. A registry row names the live generation per pack and collection, switched in one insert. A dedicated user reads and writes only this database.
3. **Scoring (test first).** Dense: exact cosine distance over the role-filtered rows. Sparse: BM25 with the document-side term weights already produced by `app/search/sparse.py` and inverse document frequency computed per generation at compile time, which replaces the server-side `idf` modifier. Trigram matching for column values as today. Fuse the ranked lists with RRF using the constant Qdrant uses, so results are comparable. Unit tests fix the scores of a small hand-computed corpus.
4. **Measure.** Compile both development packs into both engines with the same vectors and run `jobs.retrieval_eval` on the English and Vietnamese sets; record recall at the cut-offs the eval already uses, and the median and 95th-percentile latency of the retrieve node, in `docs/eval/search-engine-report.md`. Also measure a synthetic collection of 100 000 column values to know where exact search stops being acceptable.
5. **Decide.** The switch happens only if recall on every set is at least Qdrant's and the retrieve node's 95th percentile stays under one second on the reference machine. Otherwise stop here: keep Qdrant as the internal process, record the result in DECISIONS §14, and continue with task 8 only.
6. **Switch.** Make ClickHouse the engine, recompile on upgrade (a schema change marks packs as needing a compile and the application compiles on start when vectors are missing), and run the pack evals once to confirm no regression.
7. **Remove Qdrant.** Delete the Qdrant process and binary from the image, the `qdrant` Compose service, `infra/qdrant/`, `QDRANT_URL` and the image audit job; update the documentation. Record the image size and idle memory again.
8. **Documents switch (test first).** A setting, on by default. Off: the Documents page and its endpoints are absent, the compiler builds no `kb_docs`, the retrieve node skips it and `metadata_qa` answers from the glossary alone. Turning it off with documents present keeps the files and asks for confirmation; turning it on again reindexes them at the next compile. The setup gains the Documents step with upload available in place.

## Contracts

- `search.<collection>__<generation>` tables and `search.live` registry.
- Settings group `documents` with `enabled`.
- `engine.py` is the only search interface the agent and compiler import.

## Verification

```bash
uv sync --project apps/api --frozen
uv run --project apps/api pytest -c apps/api/pyproject.toml
docker compose run --rm jobs python -m jobs.compile_pack --pack ecommerce_twin
docker compose run --rm jobs python -m jobs.retrieval_eval --pack ecommerce_twin
docker compose run --rm jobs python -m jobs.retrieval_eval --pack iowa_liquor
docker compose run --rm jobs python -m jobs.eval --pack ecommerce_twin   # billable, once, after the switch
```

## Definition of done

- The report shows recall and latency for both engines and states the decision.
- If switched: `docker exec fitcher ps` shows web, api and ClickHouse only, and both pack evals hold their baselines.
- With documents off, no document endpoint answers and a definition question is still answered from the glossary.

## Risks and open questions

- Exact search over a very large `column_values` collection. Default: cap indexed values per column as the compiler already does and report the measured limit; a vector index is a later change.
- BM25 parity with Qdrant's `idf` modifier is approximate. Default: judge by recall on the eval sets, not by score equality.
- A second search migration after Phase 9C costs time for no visible feature. Default: the measurement of task 4 is small and decides it; the fallback is already built.

## Branch and PR split

`chore/api/separate-search-engine-interface` (task 1), `feat/api/search-packs-in-clickhouse` (2 to 5), `chore/infra/remove-qdrant` (6, 7), `feat/web/make-documents-optional` (8).
