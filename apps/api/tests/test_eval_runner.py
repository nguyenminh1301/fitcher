"""Running an eval set through the graph, one case at a time."""

from dataclasses import replace
from datetime import date
import time

from agent_fixtures import GOOD_SQL, deps, extraction_reply, good_output, routing_reply
from fakes import FakeRunner
import pytest

from app.data.clickhouse import QueryError, QueryOutput
from app.eval.cases import EvalSet
from app.eval.runner import CaseTimeout, call_with_timeout, reference_result, run_eval
from app.packs.models import EvalCase, EvalExpected, EvalPeriod

Q1_2024 = EvalPeriod(label="Q1 2024", start="2024-01-01", end="2024-04-01")
Q1_2025 = EvalPeriod(label="Q1 2025", start="2025-01-01", end="2025-04-01")
REFERENCE_SQL = "SELECT widget_name, sum(sale_amount) AS widget_revenue FROM marts.widget_sales GROUP BY widget_name"


def _case(case_id: str, **updates) -> EvalCase:
    case = EvalCase(
        id=case_id, question="Top 10 widgets in Q1 2024 vs Q1 2025", language="en", category="two_period_compare",
        role="viewer",
        expected=EvalExpected(
            intent="data_query", outcome="answer", periods=[Q1_2024, Q1_2025], top_n=10, rank_by="widget_revenue",
            dataset="widget_sales", columns=["widget_name"],
        ),
        expected_sql=REFERENCE_SQL, status="approved", evidence=[{"kind": "manual", "ref": "fixture"}], confidence=1.0,
    )
    return case.model_copy(update=updates)


def _inactive(case_id: str) -> EvalCase:
    expected = EvalExpected(intent="out_of_scope", outcome="deny")
    return _case(case_id, category="out_of_scope", expected=expected, expected_sql=None, active_from_phase=9)


def _set(*cases: EvalCase) -> EvalSet:
    return EvalSet(reference_date=date(2026, 1, 15), cases=list(cases))


def _run(eval_set: EvalSet, agent, timeout: float = 5.0):
    return run_eval("minimal", eval_set, agent, timeout=timeout, threshold=0.8)


def test_runs_active_cases_and_skips_inactive_ones():
    agent = deps([routing_reply(), extraction_reply(), GOOD_SQL, "Blue led."], runner=FakeRunner(runs=[good_output(), good_output()]))

    run = _run(_set(_inactive("later"), _case("now")), agent)

    assert [score.case_id for score in run.cases] == ["later", "now"]
    assert {layer.status for layer in run.cases[0].layers.values()} == {"not_scored"}
    assert run.cases[1].layers["execution"].status == "pass"
    assert len(agent.llm.calls) == 4
    assert (run.pack, run.reference_date, run.threshold) == ("minimal", date(2026, 1, 15), 0.8)


def test_reference_sql_runs_as_its_own_trace():
    agent = deps([routing_reply(), extraction_reply(), GOOD_SQL, "Blue led."], runner=FakeRunner(runs=[good_output(), good_output()]))

    run = _run(_set(_case("now")), agent)

    assert agent.runner.calls[0] == ("run", REFERENCE_SQL, "eval-reference-now")
    trace_ids = {call[2] for call in agent.runner.calls[1:]}
    assert trace_ids == {run.cases[0].trace_id}


def test_expected_rows_become_a_typed_reference():
    rows = [{"widget_name": "Widget 0", "widget_revenue_q1_2025": 10.5, "flagged": False, "note": None}]
    case = _case("rows", expected_sql=None, expected_rows=rows)

    result = reference_result(case, deps([]))

    assert [(column.name, column.type, column.role) for column in result.columns] == [
        ("widget_name", "string", "dimension"),
        ("widget_revenue_q1_2025", "number", "measure"),
        ("flagged", "boolean", "dimension"),
        ("note", "string", "dimension"),
    ]
    assert result.rows == [["Widget 0", 10.5, False, None]]


def test_reference_query_error_is_recorded_and_the_run_continues():
    runner = FakeRunner(runs=[QueryError("sql", "Unknown identifier", "qid-ref", 47), good_output()])
    agent = deps([routing_reply(), extraction_reply(), GOOD_SQL, "Blue led."], runner=runner)

    run = _run(_set(_case("broken_reference")), agent)

    assert run.reference_errors == ["broken_reference: Unknown identifier"]
    execution = run.cases[0].layers["execution"]
    assert (execution.status, execution.reason) == ("fail", "reference: Unknown identifier")
    assert run.cases[0].layers["extraction"].status == "pass"


def test_exception_in_one_case_does_not_stop_the_run():
    searches = []

    def search(index: str, body: dict) -> list[dict]:
        searches.append(index)
        if len(searches) == 1:
            raise KeyError("payload")
        return []

    runner = FakeRunner(runs=[good_output(), good_output(), good_output()])
    agent = deps([routing_reply(), extraction_reply(), routing_reply(), extraction_reply(), GOOD_SQL, "Blue led."], runner=runner, search=search)

    run = _run(_set(_case("crashes"), _case("survives")), agent)

    crashed, survived = run.cases
    assert crashed.error.startswith("KeyError")
    assert {crashed.layers[layer].status for layer in ("extraction", "retrieval", "execution")} == {"fail"}
    assert crashed.layers["execution"].reason == crashed.error
    assert crashed.layers["intent"].status == "fail"
    assert survived.error is None
    assert survived.layers["execution"].status == "pass"


def test_call_with_timeout_returns_the_value_or_raises():
    assert call_with_timeout(lambda: 42, 1.0) == 42
    with pytest.raises(ValueError, match="bad"):
        call_with_timeout(lambda: (_ for _ in ()).throw(ValueError("bad")), 1.0)
    with pytest.raises(CaseTimeout):
        call_with_timeout(lambda: time.sleep(0.3), 0.05)


def test_case_timeout_marks_the_case_and_continues():
    def slow_extraction(prompt: str) -> dict:
        time.sleep(0.3)
        return extraction_reply()

    agent = deps([routing_reply(), slow_extraction], runner=FakeRunner(runs=[good_output()]))

    run = _run(_set(_case("slow")), agent, timeout=0.05)

    assert run.cases[0].error == "timed out after 0.05s"
    assert run.cases[0].layers["execution"].status == "fail"


def test_case_records_elapsed_seconds():
    ticks = iter([10.0, 12.5])
    agent = deps([routing_reply(), extraction_reply(), GOOD_SQL, "Blue led."], runner=FakeRunner(runs=[good_output(), good_output()]))

    run = run_eval("minimal", _set(_case("now")), agent, timeout=5.0, threshold=0.8, clock=lambda: next(ticks))

    assert run.cases[0].seconds == 2.5


def test_reference_sql_result_is_typed_by_the_pack():
    output = QueryOutput(query_id="q", columns=["widget_name"], types=["String"], rows=[("Widget 0",)])
    agent = deps([], runner=FakeRunner(runs=[output]))

    result = reference_result(_case("now"), agent)

    assert result.rows == [["Widget 0"]]


def test_each_case_runs_as_its_role_with_that_roles_runner():
    agent = deps([routing_reply(), extraction_reply(), GOOD_SQL, "Blue led.", routing_reply(), extraction_reply(), GOOD_SQL, "Blue led."], runner=None)
    pack = agent.compiled.pack
    auditor = pack.policies.roles[0].model_copy(update={"id": "auditor"})
    policies = pack.policies.model_copy(update={"roles": [*pack.policies.roles, auditor]})
    agent = replace(agent, compiled=agent.compiled.model_copy(update={"pack": pack.model_copy(update={"policies": policies})}))
    runners: dict[str, FakeRunner] = {}

    def runner_for(role: str) -> FakeRunner:
        return runners.setdefault(role, FakeRunner(runs=[good_output(), good_output()]))

    run = run_eval(
        "minimal", _set(_case("first", role="viewer"), _case("second", role="auditor")), agent,
        timeout=5.0, threshold=0.8, runner_for=runner_for,
    )

    assert set(runners) == {"viewer", "auditor"}
    assert all(len(runner.calls) >= 2 for runner in runners.values())
    roles_searched = {role for _, body, _ in agent.search.searches for role in body_roles(body)}
    assert roles_searched == {"viewer", "auditor"}
    assert len(run.cases) == 2


def body_roles(body: dict) -> list[str]:
    text = str(body)
    return [role for role in ("viewer", "auditor") if f"'{role}'" in text]


def test_deny_case_runs_no_reference_query():
    expected = EvalExpected(intent="data_query", outcome="deny", metrics=["widget_revenue"], dataset="widget_sales")
    case = _case("blocked", category="unauthorized", role="nobody", expected=expected, expected_sql=None, active_from_phase=6)
    agent = deps([routing_reply(), extraction_reply()], runner=FakeRunner())

    run = _run(_set(case), agent)

    assert agent.runner.calls == []
    assert run.cases[0].layers["execution"].status == "pass"
    assert run.reference_errors == []


def _follow_up_case(case_id: str = "last_year") -> EvalCase:
    q1_2023 = EvalPeriod(label="Q1 2023", start="2023-01-01", end="2023-04-01")
    expected = EvalExpected(
        intent="data_query", outcome="answer", periods=[q1_2023, Q1_2024], top_n=10, rank_by="widget_revenue",
        dataset="widget_sales", columns=["widget_name"],
    )
    return _case(
        case_id, category="follow_up", question="What about last year?", expected=expected,
        previous_question="Top 10 widgets in Q1 2024 vs Q1 2025",
    )


def test_follow_up_case_asks_its_previous_question_first():
    follow_up = extraction_reply(periods=[], previous_periods={"unit": "year", "offset": -1})
    agent = deps(
        [routing_reply(), extraction_reply(), GOOD_SQL, "Blue led.", routing_reply(), follow_up, GOOD_SQL, "Blue led again."],
        runner=FakeRunner(runs=[good_output(), good_output(), good_output()]),
    )

    [score] = _run(_set(_follow_up_case()), agent).cases

    assert [score.layers[layer].status for layer in ("intent", "extraction", "execution")] == ["pass", "pass", "pass"]
    prompts = [call.prompt for call in agent.llm.calls if call.schema is not None and call.schema.__name__ == "Extraction"]
    assert "Earlier turns" not in prompts[0]
    assert "Earlier turns" in prompts[1] and "Top 10 widgets in Q1 2024 vs Q1 2025" in prompts[1] and "Blue led." in prompts[1]


def test_a_failed_previous_question_fails_the_case():
    agent = deps([RuntimeError("gateway exploded")], runner=FakeRunner(runs=[good_output()]))

    [score] = _run(_set(_follow_up_case()), agent).cases

    assert score.error == "previous question: RuntimeError: gateway exploded"
    assert score.layers["execution"].status == "fail"


def test_an_out_of_scope_case_needs_no_reference_query():
    expected = EvalExpected(intent="out_of_scope", outcome="answer")
    case = _case("poem", category="out_of_scope", question="Write a poem", expected=expected, expected_sql=None)
    agent = deps([routing_reply("out_of_scope"), "I answer data questions."], runner=FakeRunner())

    run = _run(_set(case), agent)

    assert run.cases[0].layers["execution"].status == "pass"
    assert run.reference_errors == [] and agent.runner.calls == []


def test_a_chart_edit_case_redraws_the_previous_answer_without_sql():
    expected = EvalExpected(intent="chart_edit", outcome="answer")
    case = _case("as_line", category="chart_edit", question="Draw it as a line", expected=expected, expected_sql=None,
                 previous_question="Top 10 widgets in Q1 2024 vs Q1 2025")
    agent = deps([routing_reply(), extraction_reply(), GOOD_SQL, "Blue led.", routing_reply("chart_edit", chart_type="line")],
                 runner=FakeRunner(runs=[good_output()]))

    [score] = _run(_set(case), agent).cases

    assert (score.layers["intent"].status, score.layers["execution"].status) == ("pass", "pass")
    assert [call[0] for call in agent.runner.calls] == ["explain", "run"]
