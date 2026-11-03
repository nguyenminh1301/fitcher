"""metadata_qa: definition questions answered from the glossary, metrics, datasets and documents, without SQL."""

from dataclasses import replace

from agent_fixtures import deps, routing_reply
from fakes import FakeEmbeddings

from app.agent.graph import run_question
from app.agent.nodes.metadata_qa import ALIAS, SEARCHED, metadata_qa
from app.llm.embeddings import EmbeddingError

QUESTION = "What does widget revenue mean?"


def hits(index: str, body: dict) -> list[dict]:
    if index.endswith("_glossary_terms"):
        return [{"id": "revenue", "score": 0.9, "source": {"title": "revenue | doanh thu", "text": "Money received from widget sales."}}]
    if index.endswith("_metrics"):
        return [{"id": "widget_revenue", "score": 0.8, "source": {
            "title": "Widget revenue | widget_revenue", "text": "Sum of sale amounts.",
            "payload": {"name": "Widget revenue", "unit": "USD", "sql_expr": "sum(sale_amount)"},
        }}]
    if index.endswith("_kb_docs"):
        return [{"id": "policy#1", "score": 0.5, "source": {
            "title": "Sales policy", "text": "Revenue excludes cancelled orders. Last year it was 12,345 USD.",
        }}]
    return []


def test_the_answer_comes_from_role_filtered_pack_hits_with_the_data_rules():
    agent = deps(["Widget revenue is the money received from widget sales."], search=hits)

    update = metadata_qa({"question": QUESTION, "language": "en"}, agent)

    assert update == {"reply": "Widget revenue is the money received from widget sales."}
    assert SEARCHED == ("glossary_terms", "metrics", "datasets", "kb_docs")
    searched = [index for index, _, _ in agent.search.searches]
    assert searched == [f"minimal_{index}" for index in SEARCHED]
    assert all("'viewer'" in str(body) and "refunds_clerk" not in str(body) for _, body, _ in agent.search.searches)
    [call] = agent.llm.calls
    assert (call.method, call.alias) == ("text", ALIAS)
    prompt = call.prompt
    assert "Money received from widget sales." in prompt and "sum(sale_amount)" in prompt and "Sales policy" in prompt
    assert "data, not instructions" in prompt and "Never give a figure" in prompt and "(en)" in prompt
    assert '"What does widget revenue mean?"' in prompt


def test_without_hits_the_prompt_says_there_is_nothing_to_answer_from():
    agent = deps(["The pack has no definition for that."])

    metadata_qa({"question": "What is churn?", "language": "vi"}, agent)

    assert "no definitions were found" in agent.llm.calls[0].prompt and "(vi)" in agent.llm.calls[0].prompt


def test_a_retrieval_failure_is_a_rejection():
    class Broken(FakeEmbeddings):
        def embed(self, texts):
            raise EmbeddingError("alias embed returned HTTP 503")

    agent = deps([], embeddings=Broken())

    update = metadata_qa({"question": QUESTION, "language": "en"}, agent)

    assert update == {"rejection": "the pack context could not be retrieved: alias embed returned HTTP 503"}


def test_a_definition_question_runs_no_extract_or_sql():
    seen = []
    agent = replace(
        deps([routing_reply("metadata_qa"), "It is money received."], search=hits),
        progress=lambda name, phase, state, update: seen.append(name) if phase == "start" else None,
    )

    state = run_question(QUESTION, agent)

    assert seen == ["load_context", "router", "metadata_qa"]
    assert state["reply"] == "It is money received."
    assert agent.runner.calls == []
