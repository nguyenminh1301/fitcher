"""Search index names, mappings, documents and queries for a pack."""

from conftest import SCHEMA_DIR
from fakes import FakeEmbeddings, FakeSearch
import pytest

from app.packs.loader import load_pack
from app.packs.search_indices import (
    HYBRID_PIPELINE,
    ColumnValue,
    build_documents,
    generation_of,
    hybrid_query,
    index_body,
    search_pack,
    value_query,
)


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


def test_semantic_index_has_a_vector_and_folding_analyzer():
    body = index_body("glossary_terms", 1024)

    properties = body["mappings"]["properties"]
    assert properties["embedding"]["dimension"] == 1024
    assert properties["title"]["analyzer"] == "folded"
    assert body["settings"]["index"]["analysis"]["analyzer"]["folded"]["filter"] == ["lowercase", "asciifolding"]
    assert body["settings"]["index"]["knn"] is True


def test_column_values_index_is_lexical_with_a_trigram_field():
    properties = index_body("column_values", 1024)["mappings"]["properties"]

    assert "embedding" not in properties
    assert properties["title"]["fields"]["trigram"]["analyzer"] == "folded_trigram"


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


def test_hybrid_query_filters_both_subqueries_by_role():
    query = hybrid_query("doanh thu", [0.1, 0.2], ["viewer"], 5)

    lexical, semantic = query["query"]["hybrid"]["queries"]
    assert lexical["bool"]["filter"] == [{"terms": {"allowed_roles": ["viewer"]}}]
    assert semantic["knn"]["embedding"]["filter"] == {"terms": {"allowed_roles": ["viewer"]}}
    assert query["_source"] == {"excludes": ["embedding"]}


def test_value_query_is_fuzzy_and_role_filtered():
    query = value_query("Blu Widgit", ["viewer"], 5)["query"]["bool"]

    assert query["should"][0]["match"]["title"]["fuzziness"] == "AUTO"
    assert query["should"][1] == {"match": {"title.trigram": "Blu Widgit"}}
    assert query["filter"] == [{"terms": {"allowed_roles": ["viewer"]}}]


def test_search_pack_reads_every_alias_with_one_embedding():
    search = FakeSearch(search_results={"shop_metrics": [{"id": "m1", "score": 1.0, "source": {}}]})
    embeddings = FakeEmbeddings()

    results = search_pack(search, embeddings, "shop", "revenue", ["viewer"], 3)

    assert results["metrics"] == [{"id": "m1", "score": 1.0, "source": {}}]
    assert embeddings.calls == [["revenue"]]
    pipelines = {index: pipeline for index, _, pipeline in search.searches}
    assert pipelines["shop_column_values"] is None
    assert pipelines["shop_metrics"] == HYBRID_PIPELINE
    assert len(search.searches) == 6
