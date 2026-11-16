"""Compare pack search in Qdrant and in ClickHouse on the same vectors (DECISIONS §14 Search engine).

Run with ``docker compose run --rm jobs python -m jobs.compare_search_engines --pack <name> [--pack ...]``.

For each pack, every live Qdrant collection is copied, points and vectors
unchanged, into a new ClickHouse generation that is then made live, so both
engines hold identical data. The labelled questions of ``jobs.retrieval_eval``
are embedded once through ``embed`` (billable, a few thousand tokens per pack;
no chat model is called) and searched on both engines with those same vectors.
The report gives recall@5, recall@10 and nDCG@10 per collection and language,
and the time to search all six collections for one question, the search work
of the retrieve node, as the median and 95th percentile over ``--repeat`` runs
after one warm-up run.

``--synthetic N`` (repeatable) also times exact search in ClickHouse over a
column-values collection of N random values with random unit vectors of
``--dimensions``; no model is called and the table is dropped afterwards.
"""

import argparse
from collections.abc import Callable, Iterator, Sequence
import json
from pathlib import Path
import random
import statistics
import sys
import time

from app.config import SettingsError, load_settings
from app.eval.cases import EvalSetError, load_eval_set
from app.llm import clients
from app.llm.embeddings import EmbeddingError
from app.observability.tracing import trusted_pack_calls
from app.packs.compiler import CompileError, approved_pack, load_compiled
from app.packs.loader import PackValidationError, load_pack
from app.packs.search_indices import INDEX_NAMES, alias_name
from app.search import sparse
from app.search.clickhouse_index import ClickHouseSearch, search_client
from app.search.client import QdrantSearch
from app.search.engine import BM25, DENSE, TRIGRAM, SearchEngine, SearchError, point_id
from jobs.retrieval_eval import ROOT, TOP_K, Score, labelled_queries, render, totals

HITS_PER_COLLECTION = 5


def copy_pack(source: QdrantSearch, target: SearchEngine, pack: str, dimensions: int) -> dict[str, int]:
    """Copy every live collection of ``pack`` into a new live generation of ``target``; return the point counts."""
    collections = [alias_name(pack, index) for index in INDEX_NAMES]
    generation = max((g for name in collections for g in target.generations(name)), default=0) + 1
    counts: dict[str, int] = {}
    for name in collections:
        target.create(name, generation, dimensions)
        counts[name] = target.write(name, source.live_points(name, with_vectors=True), generation)
    target.switch_live({name: generation for name in collections})
    return counts


def percentile(values: Sequence[float], share: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, round(share * (len(ordered) - 1)))]


def timed(call: Callable[[], object], repeat: int) -> list[float]:
    call()
    times = []
    for _ in range(repeat):
        started = time.perf_counter()
        call()
        times.append((time.perf_counter() - started) * 1000)
    return times


def compare_pack(engines: dict[str, SearchEngine], embeddings, pack: str, packs_dir: Path, repeat: int) -> dict:
    cases = load_eval_set(approved_pack(load_pack(packs_dir / pack))).cases
    queries = labelled_queries(cases)
    texts = list(dict.fromkeys(query.text for query in queries))
    with trusted_pack_calls():
        vectors = dict(zip(texts, embeddings.embed(texts), strict=True)) if texts else {}
    roles = {query.text: query.role for query in queries}
    result: dict = {"pack": pack, "questions": len(texts), "engines": {}}
    for name, engine in engines.items():
        scores = [
            Score(query, [hit["id"] for hit in engine.query(alias_name(pack, query.index), query.text, vectors[query.text], [query.role], TOP_K)])
            for query in queries
        ]

        def every_collection(text: str, engine: SearchEngine = engine) -> None:
            for index in INDEX_NAMES:
                engine.query(alias_name(pack, index), text, vectors[text], [roles[text]], HITS_PER_COLLECTION)

        times = [ms for text in texts for ms in timed(lambda text=text: every_collection(text), repeat)]
        result["engines"][name] = {
            "report": totals(scores),
            "latency_ms": {"median": statistics.median(times), "p95": percentile(times, 0.95), "samples": len(times)},
        }
    return result


def synthetic_points(count: int, dimensions: int, seed: int) -> Iterator[dict]:
    rng = random.Random(seed)
    syllables = ["ka", "lo", "mi", "ra", "to", "ve", "su", "ne", "do", "pi", "an", "or", "el", "ti", "bu"]
    for number in range(count):
        value = " ".join("".join(rng.choices(syllables, k=rng.randint(2, 4))) for _ in range(rng.randint(1, 3)))
        raw = [rng.gauss(0.0, 1.0) for _ in range(dimensions)]
        norm = sum(item * item for item in raw) ** 0.5
        title = f"{value} {value}"
        yield {
            "id": point_id(f"bench.{number}"),
            "vector": {
                DENSE: [item / norm for item in raw],
                BM25: sparse.document_vector(sparse.terms(title), 4.0),
                TRIGRAM: sparse.document_vector(sparse.trigrams(value), 1.0),
            },
            "payload": {"id": f"bench.{number}", "type": "column_value", "allowed_roles": ["analyst"], "title": value},
        }


def synthetic(engine: ClickHouseSearch, count: int, dimensions: int, repeat: int) -> dict:
    collection = f"benchmark{count}_column_values"
    for generation in engine.generations(collection):
        engine.drop(collection, generation)
    engine.create(collection, 1, dimensions)
    try:
        started = time.perf_counter()
        engine.write(collection, synthetic_points(count, dimensions, seed=count), 1)
        load_seconds = time.perf_counter() - started
        engine.switch_live({collection: 1})
        probes = [next(synthetic_points(1, dimensions, seed=seed)) for seed in range(10)]
        times: list[float] = []
        for probe in probes:
            text = probe["payload"]["title"]
            times += timed(lambda: engine.query(collection, text, probe["vector"][DENSE], ["analyst"], 5), repeat)
        return {"values": count, "load_seconds": load_seconds,
                "latency_ms": {"median": statistics.median(times), "p95": percentile(times, 0.95), "samples": len(times)}}
    finally:
        engine.drop(collection, 1)


def render_comparison(result: dict) -> str:
    lines = [f"## {result['pack']} ({result['questions']} questions)", ""]
    for name, item in result["engines"].items():
        latency = item["latency_ms"]
        lines += [render(item["report"], name), "",
                  f"Six collections per question on {name}: median {latency['median']:.1f} ms, "
                  f"p95 {latency['p95']:.1f} ms over {latency['samples']} runs.", ""]
    return "\n".join(lines)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--pack", action="append", default=[])
    parser.add_argument("--packs-dir", type=Path, default=ROOT / "packs")
    parser.add_argument("--repeat", type=int, default=5)
    parser.add_argument("--synthetic", type=int, action="append", default=[])
    parser.add_argument("--dimensions", type=int, default=1024)
    parser.add_argument("--json", type=Path, help="write the results as JSON to this file")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    results: dict = {"packs": [], "synthetic": []}
    try:
        settings = load_settings()
        qdrant = QdrantSearch(settings.qdrant_url)
        clickhouse = ClickHouseSearch(search_client())
        if args.pack:
            clients.bootstrap()
        for pack in args.pack:
            compiled = load_compiled(Path(settings.compiled_pack_dir), pack)
            counts = copy_pack(qdrant, clickhouse, pack, compiled.embedding_dimensions)
            print(f"{pack}: copied {', '.join(f'{name} {count}' for name, count in counts.items())}")
            embeddings = clients.embedding_client(compiled.embedding_dimensions)
            result = compare_pack({"qdrant": qdrant, "clickhouse": clickhouse}, embeddings, pack, args.packs_dir, args.repeat)
            results["packs"].append(result)
            print(render_comparison(result))
        for count in args.synthetic:
            item = synthetic(clickhouse, count, args.dimensions, args.repeat)
            results["synthetic"].append(item)
            latency = item["latency_ms"]
            print(f"Synthetic column values {count}: loaded in {item['load_seconds']:.1f} s, one query median "
                  f"{latency['median']:.1f} ms, p95 {latency['p95']:.1f} ms.")
    except (SettingsError, CompileError, PackValidationError, EvalSetError, EmbeddingError, SearchError, RuntimeError) as error:
        print(error, file=sys.stderr)
        return 1
    if args.json:
        args.json.write_text(json.dumps(results, ensure_ascii=False, indent=2, default=lambda item: item.__dict__), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
