# ecommerce_twin retrieval: OpenSearch and Qdrant

Measured on 2026-11-04 with `python -m jobs.retrieval_eval --pack ecommerce_twin` (DECISIONS §5, Phase 9C).
Each approved eval case gives a labelled query per collection: its `expected_sources`, and for a data question its labelled dataset, columns and metrics.
The question is searched as the case's role, 10 hits per collection; recall@5 is what the agent keeps per term.
"Before" is the OpenSearch generation the pack was compiled into (hybrid BM25 and kNN with min-max normalisation, fuzzy and trigram value matching); "after" is the Qdrant generation 1 compiled from the same pack (dense `embed` and BM25 sparse vectors fused with RRF, character trigrams on column values).
The `kb_docs` collection has no documents until Phase 10, so it has no labelled query.

| Collection | Language | Queries | Recall@5 before | Recall@5 after | Recall@10 before | Recall@10 after | nDCG@10 before | nDCG@10 after |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| glossary_terms | all | 8 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| glossary_terms | en | 4 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| glossary_terms | vi | 4 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| metrics | all | 32 | 0.969 | 0.969 | 1.000 | 1.000 | 0.856 | 0.874 |
| metrics | en | 16 | 1.000 | 1.000 | 1.000 | 1.000 | 0.962 | 0.962 |
| metrics | vi | 16 | 0.938 | 0.938 | 1.000 | 1.000 | 0.750 | 0.786 |
| datasets | all | 26 | 0.583 | 0.583 | 0.712 | 0.731 | 0.493 | 0.543 |
| datasets | en | 14 | 0.702 | 0.702 | 0.738 | 0.774 | 0.541 | 0.635 |
| datasets | vi | 12 | 0.444 | 0.444 | 0.681 | 0.681 | 0.437 | 0.436 |
| column_values | all | 6 | 0.917 | 1.000 | 1.000 | 1.000 | 0.895 | 0.867 |
| column_values | en | 3 | 0.833 | 1.000 | 1.000 | 1.000 | 0.939 | 0.761 |
| column_values | vi | 3 | 1.000 | 1.000 | 1.000 | 1.000 | 0.850 | 0.973 |

Recall@5 and recall@10 are not lower in any collection or language; column values gain recall@5 (0.917 to 1.000), and nDCG@10 rises for metrics and datasets.
nDCG@10 is lower for English column values (0.939 to 0.761): every labelled value is now in the top 5, but some below another value of the same column.

The weakest collection on both engines is `datasets`, mostly because the dataset document (`sales_lines`, `returns_fact`) ranks below its column documents for a whole question; retrieval of the question's own terms in the agent is unaffected (the pack eval scores retrieval at 100%).

## Pack eval

`python -m jobs.eval --pack ecommerce_twin --baseline packs/ecommerce_twin/eval_baseline.json` on Qdrant: execution match 91% (41/45), threshold 80% met; against the baseline, extraction 20/22, retrieval 22/22 and execution 20/22, delta 0 on every layer.
All eight definition cases pass, each answered from every labelled source.

## Document answers

Heading-aware chunks, a reranker over the top `kb_docs` hits and cited sources in definition answers were not adopted: `kb_docs` holds no document until the Documents API of Phase 10, so no measurement can show a gain, and the definition cases already reach recall 1.0 from the glossary, metrics and datasets.
Phase 10 indexes documents into this collection and is where they can be measured.
