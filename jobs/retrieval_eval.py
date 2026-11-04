"""Measure search quality per collection on a pack's labelled eval questions.

Run with ``docker compose run --rm api python -m jobs.retrieval_eval --pack <name>``.
Each approved eval case gives one labelled query per collection: its
``expected_sources`` (``<index>:<key>``, see ``app.packs.search_indices.source_id``),
and for a data question its labelled dataset and columns (``datasets``) and
metrics (``metrics``). The question is searched as the case's role in the
live aliases of the compiled pack, ``TOP_K`` hits per collection, and the
report gives recall@5 (the agent keeps five hits per term), recall@10 and
nDCG@10 per collection and language, with every query that missed a source.

The questions are embedded once through ``embed`` (billable; they are
reviewed pack content, so the request carries ``trusted_pack`` screening
metadata); no chat model is called. ``--json`` writes the report and
``--compare`` prints a before/after table against an earlier JSON report.
"""

import argparse
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
import json
import math
from pathlib import Path
import sys

from app.config import SettingsError, load_settings
from app.eval.cases import EvalSetError, load_eval_set
from app.llm.embeddings import EmbeddingError, LiteLLMEmbeddings
from app.observability.tracing import trusted_pack_calls
from app.packs.compiler import CompileError, approved_pack, load_compiled
from app.packs.loader import PackValidationError, load_pack
from app.packs.models import EvalCase
from app.packs.search_indices import INDEX_NAMES, OpenSearchPack, alias_name, source_id
from app.search.opensearch import OpenSearch, SearchError

ROOT = Path(__file__).resolve().parents[1]
TOP_K = 10
KEPT = 5


@dataclass(frozen=True)
class Query:
    case_id: str
    lang: str
    index: str
    text: str
    role: str
    expected: tuple[str, ...]


@dataclass
class Score:
    query: Query
    hits: list[str]

    @property
    def found(self) -> list[str]:
        return [doc for doc in self.query.expected if doc in self.hits]

    def recall(self, k: int) -> float:
        top = set(self.hits[:k])
        return sum(doc in top for doc in self.query.expected) / len(self.query.expected)

    @property
    def ndcg(self) -> float:
        relevant = set(self.query.expected)
        dcg = sum(1 / math.log2(rank + 2) for rank, doc in enumerate(self.hits[:TOP_K]) if doc in relevant)
        ideal = sum(1 / math.log2(rank + 2) for rank in range(min(len(relevant), TOP_K)))
        return dcg / ideal


@dataclass
class Totals:
    queries: int = 0
    recall_5: float = 0.0
    recall_10: float = 0.0
    ndcg_10: float = 0.0
    missed: list[dict] = field(default_factory=list)


def labelled_queries(cases: Sequence[EvalCase]) -> list[Query]:
    queries: list[Query] = []
    for case in cases:
        by_index: dict[str, list[str]] = {}
        for label in case.expected_sources:
            index, doc_id = source_id(label)
            by_index.setdefault(index, []).append(doc_id)
        expected = case.expected
        if expected.intent == "data_query" and expected.outcome != "deny":
            if expected.dataset:
                by_index.setdefault("datasets", []).extend(
                    [expected.dataset, *(f"{expected.dataset}.{column}" for column in expected.columns)]
                )
            if expected.metrics:
                by_index.setdefault("metrics", []).extend(expected.metrics)
        for index, docs in by_index.items():
            queries.append(Query(case.id, case.language, index, case.question, case.role, tuple(dict.fromkeys(docs))))
    return queries


def measure(search, embeddings, pack: str, queries: Sequence[Query]) -> list[Score]:
    texts = list(dict.fromkeys(query.text for query in queries))
    vectors = dict(zip(texts, embeddings.embed(texts), strict=True)) if texts else {}
    return [
        Score(query, [hit["id"] for hit in search.query(alias_name(pack, query.index), query.text, vectors[query.text], [query.role], TOP_K)])
        for query in queries
    ]


def totals(scores: Sequence[Score]) -> dict[str, dict[str, Totals]]:
    """Totals per collection, for each language and ``all``."""
    groups: dict[str, dict[str, list[Score]]] = {}
    for score in scores:
        for lang in (score.query.lang, "all"):
            groups.setdefault(score.query.index, {}).setdefault(lang, []).append(score)
    result: dict[str, dict[str, Totals]] = {}
    for index in [name for name in INDEX_NAMES if name in groups]:
        result[index] = {}
        for lang, members in sorted(groups[index].items()):
            result[index][lang] = Totals(
                queries=len(members),
                recall_5=sum(score.recall(KEPT) for score in members) / len(members),
                recall_10=sum(score.recall(TOP_K) for score in members) / len(members),
                ndcg_10=sum(score.ndcg for score in members) / len(members),
                missed=[
                    {"case": score.query.case_id, "missing": [doc for doc in score.query.expected if doc not in score.hits[:KEPT]]}
                    for score in members if score.recall(KEPT) < 1 and lang == "all"
                ],
            )
    return result


def render(report: dict[str, dict[str, Totals]], backend: str) -> str:
    lines = [
        f"Retrieval on {backend}: {TOP_K} hits per collection, recall@{KEPT} is what the agent keeps.", "",
        f"| Collection | Language | Queries | Recall@{KEPT} | Recall@{TOP_K} | nDCG@{TOP_K} |", "| --- | --- | --- | --- | --- | --- |",
    ]
    for index, by_lang in report.items():
        for lang, item in by_lang.items():
            lines.append(f"| {index} | {lang} | {item.queries} | {item.recall_5:.3f} | {item.recall_10:.3f} | {item.ndcg_10:.3f} |")
    misses = [(index, miss) for index, by_lang in report.items() for miss in by_lang["all"].missed]
    if misses:
        lines += ["", f"Queries missing a source in the top {KEPT}:"]
        lines += [f"- {index} / {miss['case']}: {', '.join(miss['missing'])}" for index, miss in misses]
    return "\n".join(lines)


def compare(before: dict, after: dict[str, dict[str, Totals]]) -> str:
    lines = [
        "| Collection | Language | Recall@5 before | Recall@5 after | nDCG@10 before | nDCG@10 after |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for index, by_lang in after.items():
        for lang, item in by_lang.items():
            old = before.get("collections", {}).get(index, {}).get(lang)
            old_recall = f"{old['recall_5']:.3f}" if old else "-"
            old_ndcg = f"{old['ndcg_10']:.3f}" if old else "-"
            lines.append(f"| {index} | {lang} | {old_recall} | {item.recall_5:.3f} | {old_ndcg} | {item.ndcg_10:.3f} |")
    return "\n".join(lines)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--pack", required=True)
    parser.add_argument("--packs-dir", type=Path, default=ROOT / "packs")
    parser.add_argument("--json", type=Path, help="write the report as JSON to this file")
    parser.add_argument("--compare", type=Path, help="an earlier JSON report to print a before/after table against")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        settings = load_settings()
        compiled = load_compiled(Path(settings.compiled_pack_dir), args.pack)
        cases = load_eval_set(approved_pack(load_pack(args.packs_dir / args.pack))).cases
        backend = "opensearch"
        search = OpenSearchPack(OpenSearch(settings.opensearch_url))
        embeddings = LiteLLMEmbeddings(settings.litellm_base_url, settings.litellm_master_key, compiled.embedding_dimensions)
        with trusted_pack_calls():
            scores = measure(search, embeddings, args.pack, labelled_queries(cases))
    except (SettingsError, CompileError, PackValidationError, EvalSetError, EmbeddingError, SearchError) as error:
        print(error, file=sys.stderr)
        return 1
    report = totals(scores)
    print(render(report, backend))
    if args.compare:
        print("\n" + compare(json.loads(args.compare.read_text(encoding="utf-8")), report))
    if args.json:
        data = {"backend": backend, "collections": {index: {lang: asdict(item) for lang, item in by_lang.items()} for index, by_lang in report.items()}}
        args.json.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
