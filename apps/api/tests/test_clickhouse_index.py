"""Pack search in ClickHouse: fusion and request shape offline, and scoring on a small corpus against a live server.

The live tests run with ``SEARCH_LIVE_TEST=1`` and ``CLICKHOUSE_SEARCH_PASSWORD``
(and ``CLICKHOUSE_HOST`` when ClickHouse is not reachable as ``clickhouse``);
they create and drop tables named ``search.livetest_*``.
"""

import math
import os
import uuid

import pytest

from app.search import sparse
from app.search.clickhouse_index import ClickHouseSearch, fuse, search_client, search_statement, table_name
from app.search.engine import BM25, DENSE, TRIGRAM, SearchError, point_id


def test_fusion_adds_reciprocal_ranks_from_position_zero_with_qdrants_constant():
    fused = fuse([["a", "b", "c"], ["b", "a"]], 3)

    assert fused == [("a", pytest.approx(1 / 2 + 1 / 3)), ("b", pytest.approx(1 / 3 + 1 / 2)), ("c", pytest.approx(1 / 4))]


def test_fusion_breaks_ties_by_point_id_and_keeps_only_the_requested_size():
    assert [point for point, _ in fuse([["b"], ["a"]], 1)] == ["a"]


def test_a_collection_name_that_is_not_an_identifier_is_refused():
    assert table_name("shop_metrics", 3) == "search.`shop_metrics__3`"
    with pytest.raises(SearchError):
        table_name("shop`; DROP TABLE x", 1)


def test_the_statement_has_one_ranked_list_per_requested_vector():
    statement = search_statement("search.`shop_column_values__1`", [DENSE, BM25, TRIGRAM])

    assert statement.count("UNION ALL") == 2
    assert "{trigram:Array(UInt32)}" in statement and "{bm25:Array(UInt32)}" in statement
    assert statement.count("hasAny(allowed_roles, {roles:Array(String)})") == 3


class RecordingClient:
    """Answers the live-generation lookup and records the search statement."""

    def __init__(self, rows):
        self.rows = rows
        self.calls: list[tuple[str, dict]] = []

    def query(self, sql, parameters=None):
        self.calls.append((sql, parameters))
        rows = [(4,)] if "argMax" in sql else self.rows
        return type("Result", (), {"result_rows": rows})()


def test_query_fuses_the_ranked_lists_into_hits_with_the_pack_document_and_its_roles():
    client = RecordingClient([
        ("dense", "p1", '{"id": "m.revenue"}', ["analyst"], 0.9),
        ("dense", "p2", '{"id": "m.orders"}', ["analyst"], 0.5),
        ("bm25", "p2", '{"id": "m.orders"}', ["analyst"], 3.0),
    ])

    hits = ClickHouseSearch(client).query("shop_metrics", "orders", [1.0, 0.0], ["analyst"], 5)

    assert [(hit["id"], round(hit["score"], 4)) for hit in hits] == [("m.orders", 0.8333), ("m.revenue", 0.5)]
    assert hits[0]["source"] == {"id": "m.orders", "allowed_roles": ["analyst"]}
    sql, parameters = client.calls[-1]
    assert "search.`shop_metrics__4`" in sql
    assert parameters["roles"] == ["analyst"] and parameters["limit"] == 20
    assert parameters["bm25"] == sparse.query_vector(sparse.terms("orders"))["indices"]
    assert "trigram" not in parameters


def test_column_values_also_rank_by_character_trigrams():
    client = RecordingClient([])

    ClickHouseSearch(client).query("shop_column_values", "Electornics", [1.0], ["analyst"], 5)

    assert "trigram" in client.calls[-1][1]


def test_a_query_without_words_ranks_by_the_dense_vector_only():
    client = RecordingClient([])

    ClickHouseSearch(client).query("shop_metrics", "?!", [1.0], ["analyst"], 5)

    sql, parameters = client.calls[-1]
    assert "UNION ALL" not in sql and set(parameters) == {"vector", "roles", "limit"}


def test_a_collection_without_a_live_generation_is_a_search_error():
    class NoLive(RecordingClient):
        def query(self, sql, parameters=None):
            return type("Result", (), {"result_rows": []})()

    with pytest.raises(SearchError, match="no live generation"):
        ClickHouseSearch(NoLive([])).query("shop_metrics", "x", [1.0], ["analyst"], 5)


live = pytest.mark.skipif(os.environ.get("SEARCH_LIVE_TEST") != "1", reason="needs a running ClickHouse")


def _point(pack_id: str, dense, words: dict[str, float], roles, **payload) -> dict:
    weights = {term_index(term): weight for term, weight in words.items()}
    ordered = sorted(weights.items())
    return {
        "id": point_id(pack_id),
        "vector": {DENSE: dense, BM25: {"indices": [i for i, _ in ordered], "values": [w for _, w in ordered]}},
        "payload": {"id": pack_id, "allowed_roles": roles, **payload},
    }


def term_index(term: str) -> int:
    return sparse.query_vector([term])["indices"][0]


@pytest.fixture
def engine():
    engine = ClickHouseSearch(search_client())
    collection = f"livetest_{uuid.uuid4().hex[:8]}_metrics"
    yield engine, collection
    for generation in engine.generations(collection):
        engine.drop(collection, generation)


@live
def test_hand_computed_corpus_scores_like_qdrant(engine):
    search, collection = engine
    search.create(collection, 1, 2)
    search.write(collection, [
        _point("a", [1.0, 0.0], {"revenue": 1.0}, ["r1"]),
        _point("b", [0.0, 1.0], {"revenue": 0.5, "orders": 1.0}, ["r1"]),
        _point("c", [1.0, 1.0], {"orders": 2.0}, ["r2"]),
    ], 1)
    search.switch_live({collection: 1})

    raw = search._rows(search_statement(search._live_table(collection), [DENSE, BM25]), {
        "vector": [1.0, 0.0], "roles": ["r1"], "limit": 20, "bm25": [term_index("revenue")],
    })
    scores = {(name, point): score for name, point, _payload, _roles, score in raw}
    idf = math.log(1 + (3 - 2 + 0.5) / (2 + 0.5))
    assert scores[(BM25, point_id("a"))] == pytest.approx(1.0 * idf, rel=1e-5)
    assert scores[(BM25, point_id("b"))] == pytest.approx(0.5 * idf, rel=1e-5)
    assert scores[(DENSE, point_id("a"))] == pytest.approx(1.0, rel=1e-5)
    assert (DENSE, point_id("c")) not in scores

    hits = search.query(collection, "revenue", [1.0, 0.0], ["r1"], 3)
    assert [(hit["id"], round(hit["score"], 4)) for hit in hits] == [("a", 1.0), ("b", 0.6667)]


@live
def test_generations_switch_and_company_document_changes(engine):
    search, collection = engine
    search.create(collection, 1, 2)
    search.create(collection, 2, 2)
    search.switch_live({collection: 1})
    search.switch_live({collection: 2})
    assert search.generations(collection) == [1, 2]
    assert search.live()[collection] == 2

    search.write(collection, [
        _point("d1#0", [1.0, 0.0], {"returns": 1.0}, ["r1"], document_id="d1"),
        _point("d1#1", [0.0, 1.0], {"returns": 1.0}, ["r1"], document_id="d1"),
        _point("d2#0", [1.0, 1.0], {"returns": 1.0}, ["r1"], document_id="d2"),
    ])
    assert search.size(collection, 2) == 3
    copied = search.live_points(collection, "d1", with_vectors=True)
    assert [point["payload"]["id"] for point in copied] == sorted(["d1#0", "d1#1"], key=point_id)
    assert copied[0]["vector"][DENSE] in ([1.0, 0.0], [0.0, 1.0])

    search.set_document_roles(collection, "d1", ["r2"])
    assert {hit["id"] for hit in search.query(collection, "returns", [1.0, 0.0], ["r2"], 5)} == {"d1#0", "d1#1"}

    search.delete_document(collection, "d1")
    assert [point["payload"]["id"] for point in search.live_points(collection)] == ["d2#0"]

    search.drop(collection, 1)
    assert search.generations(collection) == [2]
