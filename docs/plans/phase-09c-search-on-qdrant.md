# Phase 9C: Search on Qdrant

## Goal

Replace OpenSearch with Qdrant for the six search collections of every pack (DECISIONS §5), keeping hybrid keyword and semantic search: each point carries a dense `embed` vector and a BM25 sparse vector, Qdrant fuses both result lists with RRF on the server, role filters are payload filters and collections are served through versioned aliases. Measure retrieval before and after the switch, documents and Vietnamese questions included, and improve document answers with reranking, heading-aware chunks and cited sources only where the measurement shows a gain.

## Scope

- The `qdrant` service in Compose in place of `opensearch`, with a pinned image tag and a data volume.
- A search client used by the compiler, `retrieve` and `metadata_qa`; the six collections per pack with versioned names and aliases.
- BM25 sparse vectors for every point, including Vietnamese text.
- Labelled document questions in the eval set and a retrieval report comparing OpenSearch with Qdrant.
- Reranking of `kb_docs` hits, heading-aware chunks and source citations in definition answers, each adopted only if it improves the report.
- Removal of OpenSearch code, configuration, image scans and documentation once the DoD holds.

## Out of scope

- The Documents API and runtime uploads (Phase 10), which index into the collections built here.
- Answering free-form questions from documents beyond definitions; numbers still come only from SQL (DECISIONS §5).
- Keeping both search engines in production use after the switch.

## Prerequisites

- Phase 9B: chunks and column values are screened before indexing.
- Phase 4 eval harness and the `ecommerce_twin` baseline.

## Deliverables

```text
compose.yaml                         # qdrant service and volume; opensearch removed after the DoD
apps/api/app/search/
  client.py                          # Qdrant client: upsert, hybrid query with RRF, payload role filter, alias swap
  sparse.py                          # BM25 sparse vectors on folded text (EN/VI)
apps/api/app/packs/search_indices.py # collection definitions for the six indices
apps/api/app/packs/compiler.py       # build a new generation, swap aliases, drop the old one
apps/api/app/agent/nodes/retrieve.py metadata_qa.py
apps/api/app/search/rerank.py        # optional, adopted only if the report improves
packs/_schema/eval.schema.json       # expected_sources for metadata_qa cases
packs/ecommerce_twin/eval.yaml       # labelled document questions in EN and VI
docs/eval/ecommerce_twin-retrieval.md
.github/workflows/security.yml       # scan the qdrant image instead of opensearch
infra/README.md
```

## Tasks

1. **Baseline on OpenSearch.** Add `metadata_qa` cases with `expected_sources` (document and chunk ids) in English and Vietnamese to the pack eval set, and record retrieval recall@k and nDCG@10 per collection on the current OpenSearch indices.
2. **Qdrant service.** Add `qdrant` with a pinned tag (v1.17 or later, for server-side RRF), a volume, loopback port binding and a healthcheck; keep `opensearch` running until task 7.
3. **Collections (test first).** One collection per index and pack, named `<pack>_<index>_v<n>` behind the alias `<pack>_<index>`, with a named dense vector of the `embed` size and a named sparse vector; payload fields `type`, `allowed_roles`, `pack` and the index's own fields, with payload indexes on `allowed_roles` and `type`.
4. **Sparse vectors (test first).** BM25 term weights from folded text (NFKC, lower case, Vietnamese diacritics both kept and folded as separate terms) with the collection's IDF computed by Qdrant; tests on English and Vietnamese term matching, exact identifiers and column names.
5. **Hybrid query (test first).** A prefetch for each vector, RRF fusion on the server, the role payload filter applied to both prefetches; the same function serves `retrieve` and `metadata_qa`. Tests use a fake client; a live test checks that a role never receives a point it may not read.
6. **Compile on Qdrant.** The compiler builds the next generation, verifies counts, swaps the alias and drops the previous generation, so a reader never sees a mixed generation; `kb_docs` is rebuilt as DECISIONS §5 Compile describes.
7. **Measure and switch.** Rerun task 1 on Qdrant and run the pack eval. When retrieval is not lower and the eval does not regress, remove OpenSearch from Compose, the api, the jobs, the Security workflow image scan and the documentation.
8. **Document answers.** Try heading-aware chunks, a reranker over the top `kb_docs` hits and cited sources in `metadata_qa` answers; keep each change only if the retrieval report improves without lowering the pack eval.

## Contracts

- Collection names, aliases and payload fields as in task 3.
- Eval case field `expected_sources` for `metadata_qa` cases.
- Settings: `QDRANT_URL`; `OPENSEARCH_URL` removed in task 7.

## Verification

```bash
uv run --project apps/api pytest -c apps/api/pyproject.toml
docker compose config --quiet
docker compose up --build --wait
docker compose run --rm api python -m jobs.compile_pack --pack ecommerce_twin
docker compose run --rm api python -m jobs.eval --pack ecommerce_twin --baseline packs/ecommerce_twin/eval_baseline.json
go run github.com/rhysd/actionlint/cmd/actionlint@v1.7.12
```

## Definition of done

| DoD item | Proof |
|---|---|
| Retrieval recall is not lower than on OpenSearch | `docs/eval/ecommerce_twin-retrieval.md` before and after |
| The pack eval does not regress | Eval report against the baseline |
| A role never receives a point it may not read | Live role-filter test |
| Reindexing serves no mixed generation | Compile test swapping aliases during queries |
| OpenSearch is gone | No `opensearch` in Compose, code, workflows or docs |

## Risks and open questions

1. **Vietnamese keyword matching.** OpenSearch used its own analyzer; BM25 here depends on the tokenizer of task 4. Default: syllable tokens with folded and unfolded forms; the task 1 Vietnamese cases decide.
2. **Reranker model.** A cross-encoder is another local model. Default: try a small multilingual reranker through ONNX Runtime, as Phase 9B does for its classifier, and adopt it only if task 8 measures a gain.
3. **Existing volumes.** Default: no data migration; compiling the pack rebuilds every collection from Git and the document registry.

## Web wiring

No feature is wired in this phase; answers keep their contract.

## Branch and PR split

- `feat/agent/measure-retrieval-baseline`: task 1.
- `feat/infra/search-collections-on-qdrant`: tasks 2-6.
- `chore/infra/remove-opensearch`: task 7.
- `feat/agent/improve-definition-answers`: task 8.
