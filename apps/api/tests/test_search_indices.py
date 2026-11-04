"""Search collection names, documents, points and the hybrid query for a pack."""

from conftest import SCHEMA_DIR
from fakes import FakeEmbeddings, FakeSearch
import pytest

from app.packs.loader import load_pack
from app.packs.search_indices import INDEX_NAMES, ColumnValue, bm25_tokens, build_documents, generation_of, points, search_pack
from app.search.client import hybrid_request, point_id, role_filter


def _add_refunds_only_role(edit_pack):
    """A second role that may read widget_refunds only."""
    edit_pack("policies.yaml", lambda data: data["roles"].append({
        **data["roles"][0], "id": "refunds_clerk", "datasets": [data["roles"][0]["datasets"][1]],
    }))
    edit_pack("datasets.yaml", lambda data: data["datasets"][1]["allowed_roles"].append("refunds_clerk"))


@pytest.mark.parametrize(("name", "expected"), [
    ("shop_metrics_v3", ("metrics", 3)),
    ("shop_column_values_v12", ("column_values", 12)),
    ("shop_metrics", None),
    ("shop_extra_metrics_v1", None),
    ("other_metrics_v1", None),
])
def test_generation_of_matches_only_the_packs_physical_indices(name, expected):
    assert generation_of("shop", name) == expected


def test_documents_carry_the_roles_granted_their_dataset_or_column(pack_dir, edit_pack):
    _add_refunds_only_role(edit_pack)
    pack = load_pack(pack_dir, schema_dir=SCHEMA_DIR)

    documents = build_documents(pack, [ColumnValue("widget_sales", "widget_name", "Blue Widget", 3)])

    metrics = {doc["id"]: doc["allowed_roles"] for doc in documents["metrics"]}
    columns = {doc["id"]: doc["allowed_roles"] for doc in documents["datasets"]}
    assert metrics == {"widget_revenue": ["viewer"], "refunded_value": ["refunds_clerk", "viewer"]}
    assert columns["widget_refunds.refund_total"] == ["refunds_clerk", "viewer"]
    assert columns["widget_sales.widget_name"] == ["viewer"]
    assert documents["column_values"][0]["allowed_roles"] == ["viewer"]
    assert documents["examples"][0]["allowed_roles"] == ["viewer"]
    assert {doc["id"]: doc["allowed_roles"] for doc in documents["glossary_terms"]} == {
        "revenue": ["viewer"], "widget": ["viewer"],
    }


def test_aggregate_only_role_sees_grouped_columns_and_its_metrics_but_no_examples(pack_dir, edit_pack):
    edit_pack("policies.yaml", lambda data: data["roles"].append({
        **data["roles"][0], "id": "summary_reader", "datasets": [{
            "dataset": "widget_sales", "columns": ["sold_on", "widget_name"],
            "aggregate_only": {"metrics": ["widget_revenue"], "min_group_size": 5},
        }],
    }))
    edit_pack("datasets.yaml", lambda data: data["datasets"][0]["allowed_roles"].append("summary_reader"))
    edit_pack("metrics.yaml", lambda data: data["metrics"].append({
        **data["metrics"][0], "id": "average_sale", "name": "Average sale", "sql_expr": "avg(sale_amount)",
    }))
    pack = load_pack(pack_dir, schema_dir=SCHEMA_DIR)

    documents = build_documents(pack, [ColumnValue("widget_sales", "widget_name", "Blue Widget", 3)])

    metrics = {doc["id"]: doc["allowed_roles"] for doc in documents["metrics"]}
    columns = {doc["id"]: doc["allowed_roles"] for doc in documents["datasets"]}
    assert metrics["widget_revenue"] == ["summary_reader", "viewer"]
    assert metrics["average_sale"] == ["viewer"]
    assert columns["widget_sales"] == ["summary_reader", "viewer"]
    assert columns["widget_sales.widget_name"] == ["summary_reader", "viewer"]
    assert columns["widget_sales.sale_amount"] == ["viewer"]
    assert documents["column_values"][0]["allowed_roles"] == ["summary_reader", "viewer"]
    assert documents["examples"][0]["allowed_roles"] == ["viewer"]


def test_glossary_document_searches_term_and_both_alias_languages(pack_dir):
    pack = load_pack(pack_dir, schema_dir=SCHEMA_DIR)

    revenue = build_documents(pack, [])["glossary_terms"][0]

    assert revenue["title"] == "revenue | doanh thu | revenue | sales"
    assert revenue["payload"]["targets"] == [{"kind": "metric", "metric": "widget_revenue"}]
    assert revenue["pack"] == "minimal"
    assert "doanh thu" in revenue["embedding_text"]


def test_value_document_ids_are_unique_per_value(pack_dir):
    pack = load_pack(pack_dir, schema_dir=SCHEMA_DIR)
    values = [ColumnValue("widget_sales", "widget_name", name, 1) for name in ("A", "B", "a")]

    ids = [doc["id"] for doc in build_documents(pack, values)["column_values"]]

    assert len(set(ids)) == 3
    assert all(doc_id.startswith("widget_sales.widget_name.") for doc_id in ids)


def test_the_hybrid_query_filters_every_prefetch_by_role_and_fuses_with_rrf():
    body = hybrid_request("shop_metrics", "doanh thu", [0.1, 0.2], ["viewer"], 5)

    assert body["query"] == {"fusion": "rrf"} and body["limit"] == 5 and body["with_payload"] is True
    assert [prefetch["using"] for prefetch in body["prefetch"]] == ["dense", "bm25"]
    assert all(prefetch["filter"] == role_filter(["viewer"]) for prefetch in body["prefetch"])
    assert role_filter(["viewer"]) == {"must": [{"key": "allowed_roles", "match": {"any": ["viewer"]}}]}
    assert body["prefetch"][0]["query"] == [0.1, 0.2]


def test_column_values_are_also_searched_by_trigrams():
    body = hybrid_request("shop_column_values", "Electornics", [0.1], ["viewer"], 5)
    assert [prefetch["using"] for prefetch in body["prefetch"]] == ["dense", "bm25", "trigram"]


def test_a_query_without_words_searches_the_dense_vector_only():
    assert [prefetch["using"] for prefetch in hybrid_request("shop_metrics", "?!", [0.1], ["viewer"], 5)["prefetch"]] == ["dense"]


def test_points_keep_the_document_as_payload_and_weigh_the_title_twice():
    documents = [{"id": "widget_revenue", "title": "widget revenue", "text": "Money", "embedding_text": "widget revenue. Money", "allowed_roles": ["viewer"]}]

    [point] = points("shop_metrics_v1", documents, [[0.5, 0.5]])

    assert point["id"] == point_id("widget_revenue")
    assert point["payload"] == {"id": "widget_revenue", "title": "widget revenue", "text": "Money", "allowed_roles": ["viewer"]}
    assert set(point["vector"]) == {"dense", "bm25"}
    assert bm25_tokens(documents[0]).count("widget") == 2


def test_search_pack_reads_every_alias_with_one_embedding():
    search = FakeSearch(search_results={"shop_metrics": [{"id": "m1", "score": 1.0, "source": {}}]})
    embeddings = FakeEmbeddings()

    results = search_pack(search, embeddings, "shop", "revenue", ["viewer"], 3)

    assert results["metrics"] == [{"id": "m1", "score": 1.0, "source": {}}]
    assert embeddings.calls == [["revenue"]]
    assert [request.alias for request in search.queries] == [f"shop_{index}" for index in INDEX_NAMES]

