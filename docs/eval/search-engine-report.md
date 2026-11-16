# Pack search in ClickHouse against Qdrant

Measured on 2026-11-16 for Phase 20 (DECISIONS §14 Search engine): can the pack's search collections move from Qdrant into ClickHouse without losing retrieval recall, in English and in Vietnamese, and does the retrieve node stay fast enough?

**Decision: switch.** ClickHouse matched or exceeded Qdrant's recall@5 and recall@10 on every collection and language of both development packs, and searching all six collections for one question took at most 177 ms at the 95th percentile, well under the one-second limit.

## Method

Both engines held identical data: `jobs.compare_search_engines` copied every live Qdrant collection of a pack, points and vectors unchanged (OpenAI `text-embedding-3-large` at 1024 dimensions, the BM25 and trigram sparse vectors of `app/search/sparse.py`), into a new ClickHouse generation and made it live.
It then embedded each pack's labelled `jobs.retrieval_eval` questions once and searched them on both engines with the same query vectors, as the case's role, ten hits per collection.
Recall@5 is what the agent keeps per term; nDCG@10 shows the order.

```bash
docker compose --profile jobs run --rm jobs python -m jobs.compare_search_engines --pack ecommerce_twin --pack iowa_liquor --repeat 5
docker compose --profile jobs run --rm jobs python -m jobs.compare_search_engines --synthetic 20000 --synthetic 50000 --synthetic 100000 --repeat 3
```

ClickHouse scores exactly, without a vector index (`app/search/clickhouse_index.py`): cosine similarity for the dense vector, and for BM25 and trigrams the document's term weights times the inverse document frequency `ln(1 + (N - n + 0.5) / (n + 0.5))`, Qdrant's `idf` modifier formula, computed over the generation at query time.
The ranked lists are fused with reciprocal rank fusion with Qdrant's constant, `1 / (2 + position)` from position 0; on a hand-computed three-point corpus both engines returned the same fused scores (Qdrant 1.20.0).

Latency is the time to search all six collections for one question, sequentially, five hits each: the search work of the retrieve node for one term.
Each question ran once to warm up and then five times; both engines were called over HTTP from the `jobs` container of the development Compose stack.
The machine was a development laptop (Intel Core i7-11800H, 16 threads, 14 GB), not the 8 GB reference machine; ClickHouse ran without the single image's four-thread profile.
Qdrant's flat time of about 36 ms per request, whatever the collection size, comes from its HTTP round trip from this client rather than from the search itself, so the latency comparison only shows that ClickHouse is not slower.

## Results

### ecommerce_twin (33 questions)

| Collection | Language | Queries | Recall@5 Qdrant | Recall@5 ClickHouse | Recall@10 Qdrant | Recall@10 ClickHouse | nDCG@10 Qdrant | nDCG@10 ClickHouse |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| glossary_terms | all | 8 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| glossary_terms | en | 4 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| glossary_terms | vi | 4 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| metrics | all | 32 | 0.938 | 0.938 | 1.000 | 1.000 | 0.877 | 0.877 |
| metrics | en | 16 | 0.938 | 0.938 | 1.000 | 1.000 | 0.960 | 0.960 |
| metrics | vi | 16 | 0.938 | 0.938 | 1.000 | 1.000 | 0.794 | 0.794 |
| datasets | all | 26 | 0.583 | 0.583 | 0.731 | 0.731 | 0.548 | 0.543 |
| datasets | en | 14 | 0.702 | 0.702 | 0.774 | 0.774 | 0.644 | 0.635 |
| datasets | vi | 12 | 0.444 | 0.444 | 0.681 | 0.681 | 0.436 | 0.436 |
| column_values | all | 6 | 0.917 | 1.000 | 1.000 | 1.000 | 0.858 | 0.852 |
| column_values | en | 3 | 1.000 | 1.000 | 1.000 | 1.000 | 0.848 | 0.731 |
| column_values | vi | 3 | 0.833 | 1.000 | 1.000 | 1.000 | 0.868 | 0.973 |

Six collections per question (20 163 column values): Qdrant median 219.4 ms, p95 222.3 ms; ClickHouse median 117.9 ms, p95 138.8 ms; 165 runs each.

### iowa_liquor (25 questions)

| Collection | Language | Queries | Recall@5 Qdrant | Recall@5 ClickHouse | Recall@10 Qdrant | Recall@10 ClickHouse | nDCG@10 Qdrant | nDCG@10 ClickHouse |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| glossary_terms | all | 3 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| glossary_terms | en | 2 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| glossary_terms | vi | 1 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| metrics | all | 24 | 0.917 | 0.917 | 1.000 | 1.000 | 0.898 | 0.883 |
| metrics | en | 18 | 0.944 | 0.944 | 1.000 | 1.000 | 0.942 | 0.922 |
| metrics | vi | 6 | 0.833 | 0.833 | 1.000 | 1.000 | 0.766 | 0.766 |
| datasets | all | 21 | 0.492 | 0.492 | 0.754 | 0.754 | 0.449 | 0.450 |
| datasets | en | 16 | 0.490 | 0.490 | 0.708 | 0.708 | 0.423 | 0.425 |
| datasets | vi | 5 | 0.500 | 0.500 | 0.900 | 0.900 | 0.531 | 0.531 |

Six collections per question (7 510 column values): Qdrant median 219.7 ms, p95 222.4 ms; ClickHouse median 135.4 ms, p95 176.8 ms; 125 runs each.

The eval sets label no `examples` or `kb_docs` sources, so those two collections were searched for latency only.

### Exact search over a large column-values collection

Random values with random unit vectors of 1024 dimensions, one query with dense, BM25 and trigram lists, ten probes run three times each after a warm-up:

| Column values | Load | Median | p95 |
| --- | --- | --- | --- |
| 20 000 | 12.6 s | 48.5 ms | 67.1 ms |
| 50 000 | 31.5 s | 86.5 ms | 98.0 ms |
| 100 000 | 62.0 s | 124.3 ms | 146.8 ms |

Time grows about linearly with the collection, as a full scan does.
At 100 000 values one query stays near 150 ms at the 95th percentile, so the retrieve node's few column-value lookups per question remain under one second; the compiler's per-column cap (`COLUMN_VALUES_TOP_K`, 10 000 by default) keeps real packs well below that.
A vector index is the later change if a pack needs far more values.

## Reading

- Recall is identical except column values, where ClickHouse finds one more value in the top five for a Vietnamese question of `ecommerce_twin`: exact dense search cannot miss a neighbour that Qdrant's approximate index can.
- nDCG@10 differs by at most 0.02 on metrics and datasets, from ties and BM25 scores in a different floating-point order; on English column values the found value sits lower in the top five.
- The decision rule was recall on every set at least Qdrant's and a 95th percentile under one second; both hold.
