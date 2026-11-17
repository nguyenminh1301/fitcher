"""Search collection names, documents, points and the hybrid query for a pack."""

from conftest import SCHEMA_DIR
from fakes import FakeEmbeddings, FakeSearch

from app.packs.loader import load_pack
from app.packs.models import AggregateOnly, DatasetGrant, PoliciesFile
from app.packs.search_indices import INDEX_NAMES, ColumnValue, bm25_tokens, build_documents, points, search_pack
from app.search.engine import point_id


def _with_role(pack, role):
    """The pack with one more role next to its reader. A pack no longer declares roles (DECISIONS §9); the
    role-scoped search still supports them, so these tests add one here."""
    datasets = [dataset.model_copy(update={"allowed_roles": [*dataset.allowed_roles, role.id]})
                if any(grant.dataset == dataset.id for grant in role.datasets) else dataset for dataset in pack.datasets.datasets]
    return pack.model_copy(update={"datasets": pack.datasets.model_copy(update={"datasets": datasets}),
                                   "policies": PoliciesFile(roles=[*pack.policies.roles, role])})


def _add_refunds_only_role(pack):
    """A second role that may read widget_refunds only."""
    reader = pack.policies.roles[0]
    return _with_role(pack, reader.model_copy(update={"id": "refunds_clerk", "datasets": [reader.datasets[1]]}))


def test_documents_carry_the_roles_granted_their_dataset_or_column(pack_dir):
    pack = _add_refunds_only_role(load_pack(pack_dir, schema_dir=SCHEMA_DIR))

    documents = build_documents(pack, [ColumnValue("widget_sales", "widget_name", "Blue Widget", 3)])

    metrics = {doc["id"]: doc["allowed_roles"] for doc in documents["metrics"]}
    columns = {doc["id"]: doc["allowed_roles"] for doc in documents["datasets"]}
    assert metrics == {"widget_revenue": ["reader"], "refunded_value": ["reader", "refunds_clerk"]}
    assert columns["widget_refunds.refund_total"] == ["reader", "refunds_clerk"]
    assert columns["widget_sales.widget_name"] == ["reader"]
    assert documents["column_values"][0]["allowed_roles"] == ["reader"]
    assert documents["examples"][0]["allowed_roles"] == ["reader"]
    assert {doc["id"]: doc["allowed_roles"] for doc in documents["glossary_terms"]} == {
        "revenue": ["reader"], "widget": ["reader"],
    }


def test_aggregate_only_role_sees_grouped_columns_and_its_metrics_but_no_examples(pack_dir, edit_pack):
    edit_pack("metrics.yaml", lambda data: data["metrics"].append({
        **data["metrics"][0], "id": "average_sale", "name": "Average sale", "sql_expr": "avg(sale_amount)",
    }))
    pack = load_pack(pack_dir, schema_dir=SCHEMA_DIR)
    pack = _with_role(pack, pack.policies.roles[0].model_copy(update={"id": "summary_reader", "datasets": [DatasetGrant(
        dataset="widget_sales", columns=["sold_on", "widget_name"],
        aggregate_only=AggregateOnly(metrics=["widget_revenue"], min_group_size=5),
    )]}))

    documents = build_documents(pack, [ColumnValue("widget_sales", "widget_name", "Blue Widget", 3)])

    metrics = {doc["id"]: doc["allowed_roles"] for doc in documents["metrics"]}
    columns = {doc["id"]: doc["allowed_roles"] for doc in documents["datasets"]}
    assert metrics["widget_revenue"] == ["reader", "summary_reader"]
    assert metrics["average_sale"] == ["reader"]
    assert columns["widget_sales"] == ["reader", "summary_reader"]
    assert columns["widget_sales.widget_name"] == ["reader", "summary_reader"]
    assert columns["widget_sales.sale_amount"] == ["reader"]
    assert documents["column_values"][0]["allowed_roles"] == ["reader", "summary_reader"]
    assert documents["examples"][0]["allowed_roles"] == ["reader"]


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


def test_points_keep_the_document_as_payload_and_weigh_the_title_twice():
    documents = [{"id": "widget_revenue", "title": "widget revenue", "text": "Money", "embedding_text": "widget revenue. Money", "allowed_roles": ["reader"]}]

    [point] = points("shop_metrics_v1", documents, [[0.5, 0.5]])

    assert point["id"] == point_id("widget_revenue")
    assert point["payload"] == {"id": "widget_revenue", "title": "widget revenue", "text": "Money", "allowed_roles": ["reader"]}
    assert set(point["vector"]) == {"dense", "bm25"}
    assert bm25_tokens(documents[0]).count("widget") == 2


def test_search_pack_reads_every_alias_with_one_embedding():
    search = FakeSearch(search_results={"shop_metrics": [{"id": "m1", "score": 1.0, "source": {}}]})
    embeddings = FakeEmbeddings()

    results = search_pack(search, embeddings, "shop", "revenue", ["reader"], 3)

    assert results["metrics"] == [{"id": "m1", "score": 1.0, "source": {}}]
    assert embeddings.calls == [["revenue"]]
    assert [request.collection for request in search.queries] == [f"shop_{index}" for index in INDEX_NAMES]



def test_example_document_carries_its_reviewed_spec(pack_dir, edit_pack):
    spec = {"dimensions": ["widget_name"], "filters": [{"column": "widget_name", "op": "in", "values": ["Blue Widget"]}], "top_n": 10}
    edit_pack("examples.yaml", lambda data: data["examples"][0].update(spec=spec))

    documents = build_documents(load_pack(pack_dir, schema_dir=SCHEMA_DIR), [])

    assert documents["examples"][0]["payload"]["spec"] == {**spec, "rank_by": None}


def test_example_document_without_a_spec_carries_none(pack_dir):
    documents = build_documents(load_pack(pack_dir, schema_dir=SCHEMA_DIR), [])

    assert documents["examples"][0]["payload"]["spec"] is None
