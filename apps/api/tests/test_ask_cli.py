"""Printing a run from ``jobs/ask.py`` and its fault-injection wrapper."""

from agent_fixtures import GOOD_SQL, deps, extraction_reply
from fake_llm import FakeLLMClient

from app.agent.graph import run_question
from jobs.ask import FaultInjectingLLM, format_table, report


def test_successful_run_prints_sql_table_warnings_and_summary(capsys):
    state = run_question("Top widgets", deps([extraction_reply(), GOOD_SQL, "Blue led."]), trace_id="trace-7")

    code = report(state)

    out = capsys.readouterr().out
    assert code == 0
    assert "Trace: trace-7" in out
    assert "SQL attempt 1 (sql-gen):\nSELECT widget_name" in out
    assert "Result (2 rows):" in out
    assert "Widget 0" in out and "10.5" in out
    assert "Summary:\nBlue led." in out


def test_rejected_question_exits_with_code_2_and_the_reason(capsys):
    state = run_question("Which widgets?", deps([extraction_reply(rank_term=None)]))

    assert report(state) == 2
    assert "Rejected: the question names no measure to report" in capsys.readouterr().err


def test_failed_run_prints_the_last_sql_and_error_and_exits_1(capsys):
    state = run_question("Top widgets", deps([extraction_reply(), "SELECT secret FROM marts.widget_sales"]))

    code = report(state)

    captured = capsys.readouterr()
    assert code == 1
    assert "SELECT secret FROM marts.widget_sales" in captured.out
    assert "-> policy error in guard" in captured.out
    assert "No result" in captured.err


def test_fault_injection_breaks_only_the_first_generated_sql():
    llm = FaultInjectingLLM(FakeLLMClient(["SELECT a FROM t", "SELECT a FROM t", "summary"]))

    assert llm.text("sql-gen", "p") == "SELECT fitcherInjectedFault() AS injected_fault, a FROM t"
    assert llm.text("sql-gen", "p") == "SELECT a FROM t"
    assert llm.text("fast", "p") == "summary"


def test_table_is_aligned_and_limited():
    table = format_table(["name", "n"], [["a", 1], ["bbb", None], ["c", 3]], limit=2)

    assert table.splitlines() == ["name | n", "-----+--", "a    | 1", "bbb  |  ", "... 1 more rows"]
