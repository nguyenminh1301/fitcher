"""Access rules of the ClickHouse users around ``agent_logs``.

The configuration tests always run. The live tests connect to a running
ClickHouse and run only with ``AGENT_LOGS_LIVE_TEST=1`` and each user's
password in the environment (``CLICKHOUSE_HOST`` defaults to localhost).
"""

import os
from pathlib import Path
import xml.etree.ElementTree as ElementTree

import pytest

USERS_DIR = Path(__file__).resolve().parents[2] / "infra" / "clickhouse" / "users.d"
TRACE_TABLES = ["runs", "events", "llm_calls", "sql_runs", "audit", "eval_reports", "trace_query_log"]
REVIEW_TABLES = ["example_proposals", "feedback", "chat_messages"]


def grants(file_name: str, user: str) -> list[str]:
    root = ElementTree.parse(USERS_DIR / file_name).getroot()
    node = root.find(f"users/{user}")
    assert node is not None, f"{user} is not defined in {file_name}"
    return [query.text.strip() for query in node.findall("grants/query")]


def test_writer_may_only_insert_into_agent_logs():
    assert grants("agent_logs.xml", "agent_logs_writer") == ["GRANT INSERT ON agent_logs.*"]


def test_trace_reader_selects_trace_tables_and_query_log_only():
    expected = [f"GRANT SELECT ON agent_logs.{table}" for table in TRACE_TABLES] + ["GRANT SELECT ON system.query_log"]
    assert grants("agent_logs.xml", "agent_logs_trace_reader") == expected


def test_review_reader_selects_review_tables_only():
    expected = [f"GRANT SELECT ON agent_logs.{table}" for table in REVIEW_TABLES]
    assert grants("agent_logs.xml", "agent_logs_review_reader") == expected


def test_no_shared_agent_user_is_configured():
    # Agent queries run as the per-role users that compile_pack creates from policies.yaml.
    assert not (USERS_DIR / "agent_readonly.xml").exists()
    compose = (USERS_DIR.parents[2] / "compose.yaml").read_text(encoding="utf-8")
    assert "agent_readonly" not in compose and "CLICKHOUSE_AGENT_USER" not in compose


def test_log_passwords_come_from_the_environment():
    root = ElementTree.parse(USERS_DIR / "agent_logs.xml").getroot()
    sources = {user.tag: user.find("password").get("from_env") for user in root.find("users")}
    assert sources == {
        "agent_logs_writer": "CLICKHOUSE_LOGS_WRITER_PASSWORD",
        "agent_logs_trace_reader": "CLICKHOUSE_TRACE_READER_PASSWORD",
        "agent_logs_review_reader": "CLICKHOUSE_REVIEW_READER_PASSWORD",
    }


def test_reader_limits_cannot_be_changed_by_a_query():
    root = ElementTree.parse(USERS_DIR / "agent_logs.xml").getroot()
    profile = root.find("profiles/agent_logs_reader")
    assert profile.find("readonly").text == "2"
    for setting in ("readonly", "max_execution_time", "max_result_rows"):
        assert profile.find(f"constraints/{setting}/const") is not None, setting


live = pytest.mark.skipif(os.environ.get("AGENT_LOGS_LIVE_TEST") != "1", reason="needs a running ClickHouse")


def connect(user: str, password_env: str):
    clickhouse_connect = pytest.importorskip("clickhouse_connect")
    return clickhouse_connect.get_client(
        host=os.environ.get("CLICKHOUSE_HOST", "localhost"),
        port=int(os.environ.get("CLICKHOUSE_HTTP_PORT", "8123")),
        username=user,
        password=os.environ[password_env],
    )


def assert_denied(client, sql: str):
    with pytest.raises(Exception, match="ACCESS_DENIED"):
        client.query(sql)


@live
def test_trace_reader_cannot_select_example_proposals():
    client = connect("agent_logs_trace_reader", "CLICKHOUSE_TRACE_READER_PASSWORD")
    client.query("SELECT count() FROM agent_logs.runs")
    client.query("SELECT count() FROM system.query_log")
    client.query("SELECT count() FROM agent_logs.trace_query_log")
    assert_denied(client, "SELECT count() FROM agent_logs.example_proposals")


@live
@pytest.mark.parametrize("setting", ["max_execution_time", "max_result_rows"])
def test_reader_query_cannot_lift_its_limits(setting):
    client = connect("agent_logs_trace_reader", "CLICKHOUSE_TRACE_READER_PASSWORD")
    # clickhouse-connect refuses a const setting before sending; the server would answer SETTING_CONSTRAINT_VIOLATION.
    with pytest.raises(Exception, match="SETTING_CONSTRAINT_VIOLATION|is readonly"):
        client.query("SELECT 1", settings={setting: 0})


@live
def test_review_reader_cannot_select_trace_tables():
    client = connect("agent_logs_review_reader", "CLICKHOUSE_REVIEW_READER_PASSWORD")
    client.query("SELECT count() FROM agent_logs.example_proposals")
    assert_denied(client, "SELECT count() FROM agent_logs.runs")


@live
def test_writer_cannot_select():
    client = connect("agent_logs_writer", "CLICKHOUSE_LOGS_WRITER_PASSWORD")
    assert_denied(client, "SELECT count() FROM agent_logs.runs")


def test_the_query_stopper_may_only_list_and_stop_queries():
    assert grants("agent_query_stopper.xml", "agent_query_stopper") == [
        "GRANT SELECT ON system.processes", "GRANT KILL QUERY ON *.*",
    ]
    root = ElementTree.parse(USERS_DIR / "agent_query_stopper.xml").getroot()
    assert root.find("users/agent_query_stopper/password").get("from_env") == "CLICKHOUSE_QUERY_STOPPER_PASSWORD"


def test_the_conversation_store_reaches_conversation_tables_and_only_writes_feedback():
    assert grants("agent_conversations.xml", "agent_conversations") == [
        "GRANT SELECT, INSERT ON agent_logs.chat_messages", "GRANT SELECT, INSERT ON agent_logs.conversations",
        "GRANT SELECT, INSERT ON agent_logs.conversation_groups", "GRANT INSERT ON agent_logs.feedback",
    ]
    root = ElementTree.parse(USERS_DIR / "agent_conversations.xml").getroot()
    assert root.find("users/agent_conversations/password").get("from_env") == "CLICKHOUSE_CONVERSATIONS_PASSWORD"


@live
def test_the_conversation_store_cannot_read_run_logs():
    client = connect("agent_conversations", "CLICKHOUSE_CONVERSATIONS_PASSWORD")
    client.query("SELECT count() FROM agent_logs.conversations")
    client.query("SELECT count() FROM agent_logs.chat_messages")
    client.query("SELECT count() FROM agent_logs.conversation_groups")
    assert_denied(client, "SELECT count() FROM agent_logs.runs")
