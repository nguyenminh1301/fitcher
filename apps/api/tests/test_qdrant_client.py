"""The Qdrant client over a mock transport, and a live role-filter check when Qdrant runs."""

import json
import os
import uuid

import httpx
import pytest

from app.search.client import QdrantSearch, SearchError, point_id


def client(handler) -> tuple[QdrantSearch, list[tuple[str, str, dict | None]]]:
    sent: list[tuple[str, str, dict | None]] = []

    def record(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else None
        sent.append((request.method, request.url.path, body))
        return handler(request, body)

    return QdrantSearch("http://qdrant:6333/", http=httpx.Client(transport=httpx.MockTransport(record))), sent


def ok(result=True) -> httpx.Response:
    return httpx.Response(200, json={"result": result, "status": "ok"})


def test_a_collection_has_named_dense_and_sparse_vectors_and_role_and_type_indexes():
    search, sent = client(lambda request, body: ok())

    search.create_collection("shop_column_values_v2", 4)

    method, path, body = sent[0]
    assert (method, path) == ("PUT", "/collections/shop_column_values_v2")
    assert body == {
        "vectors": {"dense": {"size": 4, "distance": "Cosine"}},
        "sparse_vectors": {"bm25": {"modifier": "idf"}, "trigram": {"modifier": "idf"}},
    }
    assert [(path, body["field_name"]) for _, path, body in sent[1:]] == [
        ("/collections/shop_column_values_v2/index", "allowed_roles"), ("/collections/shop_column_values_v2/index", "type"),
    ]
    search.create_collection("shop_metrics_v2", 4)
    assert "trigram" not in sent[3][2]["sparse_vectors"]


def test_aliases_move_in_one_request_and_are_read_back():
    def handler(request, body):
        if request.url.path == "/aliases":
            return ok({"aliases": [{"alias_name": "shop_metrics", "collection_name": "shop_metrics_v1"}]})
        return ok()

    search, sent = client(handler)
    actions = [{"delete_alias": {"alias_name": "shop_metrics"}}, {"create_alias": {"collection_name": "shop_metrics_v2", "alias_name": "shop_metrics"}}]

    assert search.alias_targets() == {"shop_metrics": "shop_metrics_v1"}
    search.update_aliases(actions)

    assert sent[-1] == ("POST", "/collections/aliases", {"actions": actions})


def test_points_are_written_in_batches_and_wait_until_searchable():
    search, sent = client(lambda request, body: ok({"status": "completed"}))

    assert search.upsert("shop_values_v1", ({"id": point_id(str(n)), "vector": {}, "payload": {}} for n in range(300))) == 300

    assert [len(body["points"]) for _, _, body in sent] == [256, 44]


def test_query_returns_pack_ids_scores_and_payloads():
    payload = {"id": "widget_revenue", "title": "widget revenue", "allowed_roles": ["viewer"]}
    search, sent = client(lambda request, body: ok({"points": [{"id": point_id("widget_revenue"), "score": 0.5, "payload": payload}]}))

    hits = search.query("shop_metrics", "widget revenue", [0.1], ["viewer"], 3)

    assert hits == [{"id": "widget_revenue", "score": 0.5, "source": payload}]
    assert sent[0][1] == "/collections/shop_metrics/points/query"


def test_a_failed_request_names_the_status_and_qdrant_error():
    search, _ = client(lambda request, body: httpx.Response(404, json={"status": {"error": "Not found: Collection `x` doesn't exist!"}}))

    with pytest.raises(SearchError, match="returned HTTP 404: Not found: Collection `x`"):
        search.count("x")
    search.delete_collection("x")  # a missing collection is already deleted


def test_point_ids_are_stable_uuids_of_the_document_id():
    assert point_id("widget_revenue") == point_id("widget_revenue") != point_id("widget_revenue_2")
    assert uuid.UUID(point_id("widget_revenue")).version == 5


LIVE_URL = os.environ.get("QDRANT_LIVE_URL", "")


@pytest.mark.skipif(not LIVE_URL, reason="set QDRANT_LIVE_URL to a running Qdrant to check role filtering")
def test_live_a_role_never_receives_a_point_it_may_not_read():
    search = QdrantSearch(LIVE_URL)
    name = f"rolecheck_metrics_v{uuid.uuid4().int % 10_000}"
    documents = [
        {"id": f"m{number}", "type": "metric", "title": f"widget revenue {number}", "text": "widget revenue revenue",
         "allowed_roles": roles}
        for number, roles in enumerate([["analyst"], ["marketing"], ["analyst", "marketing"], ["partner"]] * 5)
    ]
    from app.packs.search_indices import points

    search.create_collection(name, 2)
    try:
        search.upsert(name, points(name, documents, [[1.0, 0.0]] * len(documents)))
        for role in ("analyst", "marketing", "partner", "nobody"):
            hits = search.query(name, "widget revenue", [1.0, 0.0], [role], 50)
            readable = [document["id"] for document in documents if role in document["allowed_roles"]]
            assert sorted(hit["id"] for hit in hits) == sorted(readable)
            assert all(role in hit["source"]["allowed_roles"] for hit in hits)
    finally:
        search.delete_collection(name)
