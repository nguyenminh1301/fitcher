"""Scoring one eval case per layer from the final graph state."""

from agent_fixtures import GOOD_SQL, deps, extraction_reply, routing_reply

from app.agent.errors import AgentError
from app.agent.graph import run_question
from app.agent.nodes.retrieve import Hit, Retrieval
from app.agent.state import Attempt
from app.contracts.result import ColumnInfo, Result
from app.agent.nodes.gate import Denial
from app.eval.scorers import (
    LAYERS, retrieved_candidates, score_case, score_execution, score_extraction, score_retrieval,
)
from app.packs.models import EvalCase, EvalExpected, EvalPeriod

Q1_2024 = EvalPeriod(label="Q1 2024", start="2024-01-01", end="2024-04-01")
Q1_2025 = EvalPeriod(label="Q1 2025", start="2025-01-01", end="2025-04-01")


def _expected(**updates) -> EvalExpected:
    base = EvalExpected(
        intent="data_query", outcome="answer", periods=[Q1_2024, Q1_2025], top_n=10, rank_by="widget_revenue",
        dataset="widget_sales", columns=["widget_name"],
    )
    return base.model_copy(update=updates)


def _case(**updates) -> EvalCase:
    case = EvalCase(
        id="top_widgets", question="Top 10 widgets in Q1 2024 vs Q1 2025", language="en", category="two_period_compare",
        role="viewer", expected=_expected(), expected_sql="SELECT 1", status="approved",
        evidence=[{"kind": "manual", "ref": "fixture"}], confidence=1.0,
    )
    return case.model_copy(update=updates)


def _answered_state():
    return run_question("Top widgets", deps([routing_reply(), extraction_reply(), GOOD_SQL, "Blue led."]))


def _reference(rows) -> Result:
    columns = [
        ColumnInfo(name="widget", type="string", role="dimension"),
        ColumnInfo(name="revenue", type="number", role="measure"),
    ]
    return Result(columns=columns, rows=rows, row_count=len(rows))


def _hit(index: str, **source) -> Hit:
    return Hit(index=index, id="doc", score=1.0, source=source)


# extraction

def test_extraction_passes_when_periods_top_n_and_rank_by_match():
    assert score_extraction(_expected(), _answered_state()).status == "pass"


def test_extraction_reports_each_differing_field():
    score = score_extraction(_expected(top_n=5, periods=[Q1_2025]), _answered_state())

    assert score.status == "fail"
    assert "top_n: expected 5, got 10" in score.reason
    assert "periods: expected" in score.reason
    assert "rank_by" not in score.reason


def test_extraction_fails_without_extraction():
    score = score_extraction(_expected(), {"rejection": "the question could not be read: boom"})

    assert (score.status, score.reason) == ("fail", "no extraction")


# retrieval

def test_retrieval_recall_counts_dataset_and_columns():
    retrieval = Retrieval(dimension_terms={"widgets": [
        _hit("datasets", type="column", dataset="widget_sales", payload={"column": "widget_name"}),
    ]})

    score = score_retrieval(_expected(columns=["widget_name", "sale_amount"]), {"retrieval": retrieval})

    assert score.status == "fail"
    assert score.recall == 2 / 3
    assert score.reason == "missing: widget_sales.sale_amount"


def test_retrieval_counts_time_column_of_a_retrieved_dataset():
    retrieval = Retrieval(datasets=[
        _hit("datasets", type="dataset", dataset="widget_sales", payload={"time_column": "sold_on"}),
    ])

    score = score_retrieval(_expected(columns=["sold_on"]), {"retrieval": retrieval})

    assert (score.status, score.recall) == ("pass", 1.0)


def test_retrieval_counts_glossary_value_and_example_targets():
    retrieval = Retrieval(
        metric_terms={"revenue": [_hit("glossary_terms", payload={"targets": [
            {"kind": "column", "dataset": "widget_sales", "column": "sale_amount"},
        ]})]},
        values={"Blue": [_hit("column_values", dataset="widget_sales", payload={"column": "widget_name", "value": "Blue"})]},
        examples=[_hit("examples", payload={"datasets": ["widget_refunds"]})],
    )

    datasets, columns = retrieved_candidates(retrieval)

    assert datasets == {"widget_sales", "widget_refunds"}
    assert columns == {("widget_sales", "sale_amount"), ("widget_sales", "widget_name")}


def test_retrieval_not_scored_without_labels():
    score = score_retrieval(_expected(dataset=None, columns=[]), {"retrieval": Retrieval()})

    assert score.status == "not_scored"


def test_retrieval_fails_when_it_did_not_run():
    score = score_retrieval(_expected(), {"rejection": "the question names no period"})

    assert (score.status, score.reason, score.recall) == ("fail", "retrieval did not run", 0.0)


# execution

def test_execution_matches_reference():
    score = score_execution(_case(), _answered_state(), _reference([["Widget 0", 10.5], ["Widget 1", 10.5]]))

    assert score.status == "pass"


def test_execution_reports_the_comparison_reason():
    score = score_execution(_case(), _answered_state(), _reference([["Widget 0", 10.5]]))

    assert (score.status, score.reason) == ("fail", "expected 1 rows, got 2")


def test_execution_fails_with_rejection_reason():
    state = run_question("Widgets on Mars?", deps([routing_reply(), extraction_reply(filters=[{"column_term": None, "op": "=", "values": ["Mars"]}])]))

    score = score_execution(_case(), state, _reference([["Widget 0", 10.5]]))

    assert (score.status, score.reason) == ("fail", "rejected: no value of widget_sales matches \'Mars\'")


def test_execution_fails_with_last_sql_error():
    error = AgentError("sql", "execute", "Unknown identifier")
    state = {"attempts": [Attempt(alias="sql-gen", sql="SELECT x", error=error)], "result": None}

    score = score_execution(_case(), state, _reference([["Widget 0", 10.5]]))

    assert (score.status, score.reason) == ("fail", "sql error in execute: Unknown identifier")


# whole case

def test_active_case_scores_every_layer_and_leaves_intent_to_the_router():
    score = score_case(_case(), _answered_state(), _reference([["Widget 0", 10.5], ["Widget 1", 10.5]]), active=True)

    assert list(score.layers) == list(LAYERS)
    assert score.layers["intent"].status == "not_scored"
    assert [score.layers[layer].status for layer in ("extraction", "retrieval", "execution")] == ["pass", "fail", "pass"]
    assert (score.case_id, score.category, score.active) == ("top_widgets", "two_period_compare", True)


def test_inactive_case_is_not_scored_on_any_layer():
    score = score_case(_case(active_from_phase=8), {}, None, active=False)

    assert {layer.status for layer in score.layers.values()} == {"not_scored"}
    assert "active from phase 8" in score.layers["execution"].reason


# deny cases

def _deny_case():
    expected = EvalExpected(intent="data_query", outcome="deny", metrics=["widget_revenue"], dataset="widget_sales")
    return _case(category="unauthorized", expected=expected, expected_sql=None, active_from_phase=6)


def test_deny_case_passes_when_the_run_was_denied():
    denied = {"denial": Denial(dataset="widget_sales", blocked=["widget_sales"], message="Your role ...")}

    score = score_case(_deny_case(), denied, None, active=True)

    assert score.layers["execution"].status == "pass"
    assert {score.layers[layer].status for layer in ("intent", "extraction", "retrieval")} == {"not_scored"}


def test_deny_case_fails_when_the_run_answered():
    score = score_case(_deny_case(), _answered_state(), None, active=True)

    assert score.layers["execution"].status == "fail"
    assert score.layers["execution"].reason == "expected a denial, but the question was answered"
