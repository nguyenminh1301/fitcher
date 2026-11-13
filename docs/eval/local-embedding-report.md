# Local embedding models against the provider model

Measured on 2026-11-13 for Phase 14 (DECISIONS §14): can a local multilingual model run through fastembed replace the provider's embedding model without losing retrieval recall, in English and in Vietnamese?

## Method

The baseline is the provider model the packs were indexed with before Phase 14: OpenAI `text-embedding-3-large` at 1024 dimensions.
Each candidate was set as the embedding model in the app state, both development packs were compiled with it (`jobs.compile_pack`, a new Qdrant generation with the same BM25 sparse vectors), and `jobs.retrieval_eval` searched each pack's labelled eval questions as the case's role, ten hits per collection.
Recall@5 is what the agent keeps per term; nDCG@10 shows the order.

```bash
docker compose --profile jobs run --rm jobs python -m jobs.retrieval_eval --pack <pack> --json <before>.json
# set the embedding model on the Models page (PUT /models/embedding), then:
docker compose --profile jobs run --rm jobs python -m jobs.compile_pack --pack <pack>
docker compose --profile jobs run --rm jobs python -m jobs.retrieval_eval --pack <pack> --json <after>.json --compare <before>.json
```

Candidates:

- `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`, 384 dimensions, about 0.22 GB (fastembed downloads the ONNX export `Qdrant/paraphrase-multilingual-MiniLM-L12-v2-onnx-Q`). This is the default DECISIONS §14 named.
- `sentence-transformers/paraphrase-multilingual-mpnet-base-v2`, 768 dimensions, about 1.1 GB (fastembed downloads `Xenova/paraphrase-multilingual-mpnet-base-v2`). This is the next multilingual model fastembed offers.
- `intfloat/multilingual-e5-large` (1024 dimensions, 2.24 GB) was not measured: it is too large for the 8 GB reference machine next to ClickHouse.

## Results

### `ecommerce_twin`

| Collection | Language | Queries | Recall@5 OpenAI | Recall@5 MiniLM | Recall@5 mpnet | nDCG@10 OpenAI | nDCG@10 MiniLM | nDCG@10 mpnet |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| glossary_terms | all | 8 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 0.954 |
| glossary_terms | en | 4 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| glossary_terms | vi | 4 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 0.908 |
| metrics | all | 32 | 0.969 | 0.875 | 0.906 | 0.878 | 0.812 | 0.792 |
| metrics | en | 16 | 1.000 | 0.938 | 0.938 | 0.962 | 0.935 | 0.933 |
| metrics | vi | 16 | 0.938 | 0.812 | 0.875 | 0.794 | 0.690 | 0.650 |
| datasets | all | 26 | 0.583 | 0.417 | 0.494 | 0.547 | 0.430 | 0.440 |
| datasets | en | 14 | 0.702 | 0.560 | 0.631 | 0.641 | 0.544 | 0.573 |
| datasets | vi | 12 | 0.444 | 0.250 | 0.333 | 0.436 | 0.296 | 0.285 |
| column_values | all | 6 | 0.917 | 1.000 | 1.000 | 0.890 | 0.903 | 0.800 |
| column_values | en | 3 | 0.833 | 1.000 | 1.000 | 0.821 | 0.848 | 0.717 |
| column_values | vi | 3 | 1.000 | 1.000 | 1.000 | 0.959 | 0.959 | 0.884 |

### `iowa_liquor`

| Collection | Language | Queries | Recall@5 OpenAI | Recall@5 MiniLM | Recall@5 mpnet | nDCG@10 OpenAI | nDCG@10 MiniLM | nDCG@10 mpnet |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| glossary_terms | all | 3 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| glossary_terms | en | 2 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| glossary_terms | vi | 1 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| metrics | all | 24 | 0.917 | 0.917 | 0.958 | 0.883 | 0.827 | 0.860 |
| metrics | en | 18 | 0.944 | 0.944 | 0.944 | 0.922 | 0.922 | 0.896 |
| metrics | vi | 6 | 0.833 | 0.833 | 1.000 | 0.766 | 0.544 | 0.750 |
| datasets | all | 21 | 0.492 | 0.357 | 0.286 | 0.440 | 0.302 | 0.327 |
| datasets | en | 16 | 0.490 | 0.406 | 0.344 | 0.411 | 0.362 | 0.360 |
| datasets | vi | 5 | 0.500 | 0.200 | 0.100 | 0.531 | 0.109 | 0.221 |

Indexing time on the development machine: `ecommerce_twin` took 7 min 37 s with MiniLM; the mpnet run took 30 min, most of it downloading the model. `iowa_liquor` took 35 s with MiniLM and 1 min 12 s with mpnet.

## Decision

Neither local model holds recall.

- MiniLM loses recall@5 on `ecommerce_twin` metrics, in English and in Vietnamese, and on `datasets` in both packs. The largest drops are Vietnamese: `ecommerce_twin` datasets fall from 0.444 to 0.250 and `iowa_liquor` datasets from 0.500 to 0.200.
- mpnet does better than MiniLM on `ecommerce_twin`, but still loses `metrics` and `datasets` there. On `iowa_liquor` its `datasets` recall is the lowest of the three (0.286 overall, 0.100 in Vietnamese).
- Both gain on `column_values` in `ecommerce_twin` (0.917 to 1.000). Those queries rely mostly on the trigram and keyword vectors, which do not change with the model.

So the plan's fallback applies, and DECISIONS §2 and §14 record it.

- A provider's embedding model stays the default for the embed tier, and a key is then required to index a pack.
- When a provider that offers one is added, its embedding model is proposed: OpenAI `text-embedding-3-large` at 1024 dimensions, Gemini `gemini-embedding-001` at 768, or Ollama `nomic-embed-text` at 768 on a model server the user runs.
- MiniLM remains the local model used when no connected provider offers an embedding model, for example with Anthropic alone. An admin can also choose it, or mpnet, on the Models page; the page asks to confirm the full reindex that changing the model needs.

## After the measurement

Both development packs were compiled again with `text-embedding-3-large` at 1024 dimensions. `jobs.retrieval_eval` then matched the baseline on every collection and language, except `ecommerce_twin` column values, which rose from 0.917 to 1.000 at recall@5.

The pack eval ran once on the Phase 14 stack: the in-process gateway, providers in the app state, no LiteLLM Proxy service, and the classifier off.

```bash
docker compose run --rm -v ./build/eval:/app/build/eval api python -m jobs.eval --pack ecommerce_twin \
  --baseline packs/ecommerce_twin/eval_baseline.json --output-dir build/eval
```

The tiers ran the models the proxy aliases named before: `fast` and `sql-small` on `openai/gpt-5.4-mini`, `sql-gen` on `openai/gpt-5.4` and `sql-gen-hard` on `openai/gpt-5.5`.
Execution match reached 93% (42/45), above the 80% threshold, and the run exited 0. Against the baseline it did not regress on any layer: extraction 20/22 (delta 0), retrieval 22/22 (0) and execution 21/22 (+1).
