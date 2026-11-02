"""Printing a run from ``jobs/ask.py`` and its fault-injection wrapper."""

from dataclasses import replace

from agent_fixtures import GOOD_SQL, compiled_fixture, deps, extraction_reply
from fake_llm import FakeLLMClient
import pytest

from app.agent.graph import run_question
from jobs.ask import FaultInjectingLLM, choose_role, format_table, inject_fault, parse_args, report


def test_successful_run_prints_sql_table_warnings_and_summary(capsys):
    state = run_question("Top widgets", deps([extraction_reply(), GOOD_SQL, "Blue led."]))

    code = report(state)

    out = capsys.readouterr().out
    assert code == 0
    assert f"Trace: {state['trace_id']}" in out
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


def test_fault_goes_after_a_select_keyword_not_into_a_literal():
    sql = "WITH c AS (SELECT a FROM t) SELECT a FROM c WHERE name = 'SELECT'"

    assert inject_fault(sql) == "WITH c AS (SELECT a FROM t) SELECT fitcherInjectedFault() AS injected_fault, a FROM c WHERE name = 'SELECT'"
    assert inject_fault("not sql at all") == "not sql at all"


def test_fault_is_injected_past_a_backslash_escaped_quote():
    sql = r"SELECT a FROM t WHERE name = 'O\'Reilly'"

    assert inject_fault(sql) == r"SELECT fitcherInjectedFault() AS injected_fault, a FROM t WHERE name = 'O\'Reilly'"


def test_cells_keep_one_line_each():
    table = format_table(["note"], [["two\nlines\tand\x07bell"]])

    assert table.splitlines()[2] == "two\\nlines\\tand\\x07bell"


def test_table_is_aligned_and_limited():
    table = format_table(["name", "n"], [["a", 1], ["bbb", None], ["c", 3]], limit=2)

    assert table.splitlines() == ["name | n", "-----+--", "a    | 1", "bbb  |  ", "... 1 more rows"]


def test_role_defaults_to_the_first_policy_role():
    assert choose_role(compiled_fixture().pack, None) == "viewer"


def test_named_role_must_be_a_role_of_the_pack():
    assert choose_role(compiled_fixture().pack, "viewer") == "viewer"
    with pytest.raises(RuntimeError, match="'nobody' is not a role of pack minimal; roles: viewer"):
        choose_role(compiled_fixture().pack, "nobody")


def test_role_flag_is_parsed():
    assert parse_args(["Top widgets", "--role", "viewer"]).role == "viewer"
    assert parse_args(["Top widgets"]).role is None


def test_denied_question_exits_with_code_3_and_the_message(capsys):
    agent = deps([extraction_reply()])
    agent = replace(agent, role="nobody")

    state = run_question("Top widgets", agent)

    assert report(state) == 3
    assert "Denied: Your role nobody cannot read the dataset widget_sales" in capsys.readouterr().err
