"""The data_query graph end to end with fake LLM, search and ClickHouse."""

from agent_fixtures import GOOD_SQL, deps, extraction_reply, good_output
from fakes import FakeRunner

from app.agent.graph import run_question
from app.data.clickhouse import QueryError

QUESTION = "Top 10 best-selling widgets in Q1 2024 compared with Q1 2025"
SUMMARY = "Blue widgets led Q1 2025."


def sql_error(message: str = "Code: 47. DB::Exception: Unknown identifier") -> QueryError:
    return QueryError("sql", message, "qid-bad", 47)


def test_question_flows_to_a_result_and_summary():
    agent = deps([extraction_reply(), GOOD_SQL, SUMMARY])

    state = run_question(QUESTION, agent, trace_id="trace-1")

    assert state.get("rejection") is None
    spec = state["spec"]
    assert spec.metric_ids == ["widget_revenue"]
    assert spec.dimensions == ["widget_name"]
    assert [period.label for period in spec.periods] == ["Q1 2024", "Q1 2025"]
    assert (spec.top_n, spec.rank_by, spec.rank_period, spec.compare) == (10, "widget_revenue", "Q1 2025", True)
    assert state["result"].row_count == 2
    assert state["result"].columns[1].format == "currency"
    assert state["summary"] == SUMMARY
    assert [call.alias for call in agent.llm.calls] == ["fast", "sql-gen", "fast"]
    assert [call[0] for call in agent.runner.calls] == ["explain", "run"]
    assert all(call[2] == "trace-1" for call in agent.runner.calls)
    assert state["attempts"][0].query_id == "qid-ok"


def test_broken_sql_is_repaired_within_the_retry_limit():
    runner = FakeRunner(explains=[sql_error()], runs=[good_output()])
    agent = deps([extraction_reply(), "SELECT nope(widget_name) AS x FROM marts.widget_sales", GOOD_SQL, SUMMARY], runner)

    state = run_question(QUESTION, agent)

    assert state["result"] is not None
    assert [attempt.alias for attempt in state["attempts"]] == ["sql-gen", "sql-gen"]
    assert state["attempts"][0].error.category == "sql"
    retry_prompt = agent.llm.calls[2].prompt
    assert "The previous attempt failed" in retry_prompt
    assert "Unknown identifier" in retry_prompt


def test_exhausted_retries_return_the_last_sql_and_error_without_a_result():
    runner = FakeRunner(explains=[sql_error()] * 4)
    agent = deps([extraction_reply(), *[f"SELECT widget_name AS w{n} FROM marts.widget_sales" for n in range(4)]], runner)

    state = run_question(QUESTION, agent)

    assert state.get("result") is None
    assert [attempt.alias for attempt in state["attempts"]] == ["sql-gen", "sql-gen", "sql-gen", "sql-gen-hard"]
    assert state["attempts"][-1].sql.startswith("SELECT widget_name AS w3")
    assert state["attempts"][-1].error.message.startswith("Code: 47")
    assert len(state["errors"]) == 4


def test_policy_violation_stops_without_retry():
    agent = deps([extraction_reply(), "SELECT secret FROM marts.widget_sales"])

    state = run_question(QUESTION, agent)

    assert state.get("result") is None
    assert len(state["attempts"]) == 1
    assert state["attempts"][0].error.category == "policy"
    assert agent.runner.calls == []


def test_access_denied_at_execution_is_a_policy_stop():
    runner = FakeRunner(runs=[QueryError("policy", "Code: 497. ACCESS_DENIED", "qid-x", 497)])
    agent = deps([extraction_reply(), GOOD_SQL], runner)

    state = run_question(QUESTION, agent)

    assert len(state["attempts"]) == 1
    assert state["attempts"][0].error.node == "execute"


def test_zero_rows_pass_with_a_warning():
    agent = deps([extraction_reply(), GOOD_SQL, SUMMARY], FakeRunner(runs=[good_output(rows=0)]))

    state = run_question(QUESTION, agent)

    assert state["result"].row_count == 0
    assert "the query returned no rows" in state["warnings"]


def test_out_of_coverage_period_passes_with_a_warning():
    periods = [{"kind": "year", "year": 2030}]
    agent = deps([extraction_reply(periods=periods, compare=False), GOOD_SQL, SUMMARY])

    state = run_question(QUESTION, agent)

    assert state["result"] is not None
    assert any("2030 is outside the data" in warning for warning in state["warnings"])


def test_question_without_a_measure_is_rejected_before_sql():
    agent = deps([extraction_reply(rank_term=None)])

    state = run_question("Which widgets in 2024?", agent)

    assert state["rejection"] == "the question names no measure to report"
    assert [call.alias for call in agent.llm.calls] == ["fast"]
    assert "attempts" not in state or state["attempts"] == []


def test_vague_ranking_word_is_rejected_instead_of_guessed():
    agent = deps([extraction_reply(rank_term="best")])

    state = run_question("Best widgets in 2024?", agent)

    assert state["rejection"] == "'best' does not say which measure to rank by"
