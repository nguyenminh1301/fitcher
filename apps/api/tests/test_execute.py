"""The ClickHouse query runner and the explain and execute nodes, with a fake driver."""

from dataclasses import dataclass

import pytest

from app.agent.nodes.execute import execute
from app.agent.nodes.explain import explain
from app.data.clickhouse import ClickHouseRunner, QueryLimits, agent_client, classify

LIMITS = QueryLimits(max_execution_time=12, max_result_rows=345, max_memory_usage=678)


@dataclass
class FakeType:
    name: str


@dataclass
class FakeResult:
    column_names: tuple
    column_types: list
    result_rows: list


class FakeClient:
    def __init__(self, error: Exception | None = None):
        self.error = error
        self.calls: list[tuple[str, dict]] = []

    def query(self, sql, settings=None):
        self.calls.append((sql, settings))
        if self.error is not None:
            raise self.error
        return FakeResult(("widget_name", "revenue"), [FakeType("String"), FakeType("Float64")], [["Blue", 3.5]])


def runner(client: FakeClient) -> ClickHouseRunner:
    return ClickHouseRunner(client, LIMITS, new_query_id=lambda: "qid-1")


def driver_error(code: int, name: str) -> Exception:
    return Exception(
        f"Received ClickHouse exception, code: {code}, server response: Code: {code}. DB::Exception: boom. ({name}) "
        "(for url http://clickhouse:8123)"
    )


def test_execute_sends_limits_trace_id_and_query_id():
    client = FakeClient()

    result = execute(runner(client), "SELECT 1", "trace-9")

    assert result.error is None
    assert result.query_id == "qid-1"
    assert result.output.columns == ["widget_name", "revenue"]
    assert result.output.types == ["String", "Float64"]
    assert result.output.rows == [("Blue", 3.5)]
    assert client.calls == [("SELECT 1", {
        "max_execution_time": 12, "max_result_rows": 345, "max_memory_usage": 678,
        "log_comment": "trace-9", "query_id": "qid-1",
    })]


def test_explain_prefixes_the_query_and_reports_success_as_none():
    client = FakeClient()

    assert explain(runner(client), "SELECT 1", "trace-9") is None
    assert client.calls[0][0] == "EXPLAIN SELECT 1"
    assert client.calls[0][1]["log_comment"] == "trace-9"


@pytest.mark.parametrize(("code", "name", "category"), [
    (47, "UNKNOWN_IDENTIFIER", "sql"),
    (62, "SYNTAX_ERROR", "sql"),
    (43, "ILLEGAL_TYPE_OF_ARGUMENT", "sql"),
    (159, "TIMEOUT_EXCEEDED", "runtime"),
    (241, "MEMORY_LIMIT_EXCEEDED", "runtime"),
    (396, "TOO_MANY_ROWS_OR_BYTES", "runtime"),
    (497, "ACCESS_DENIED", "policy"),
    (164, "READONLY", "policy"),
])
def test_clickhouse_errors_are_classified(code, name, category):
    assert classify(driver_error(code, name)) == (category, code)


def test_connection_failure_is_a_runtime_error():
    assert classify(ConnectionRefusedError("connection refused")) == ("runtime", None)


def test_execute_error_carries_category_message_and_query_id():
    result = execute(runner(FakeClient(driver_error(47, "UNKNOWN_IDENTIFIER"))), "SELECT x", "trace-9")

    assert result.output is None
    assert result.query_id == "qid-1"
    assert result.error.category == "sql"
    assert result.error.node == "execute"
    assert result.error.message == "Code: 47. DB::Exception: boom. (UNKNOWN_IDENTIFIER)"


def test_explain_error_is_classified():
    error = explain(runner(FakeClient(driver_error(159, "TIMEOUT_EXCEEDED"))), "SELECT 1", "t")

    assert (error.category, error.node) == ("runtime", "explain")


def test_limits_come_from_the_environment_with_defaults():
    assert QueryLimits.from_env({}) == QueryLimits(30, 10_000, 2_000_000_000)
    assert QueryLimits.from_env({"QUERY_MAX_EXECUTION_TIME": "5", "QUERY_MAX_RESULT_ROWS": "50"}) == QueryLimits(
        5, 50, 2_000_000_000
    )


def test_agent_client_requires_its_password():
    with pytest.raises(RuntimeError, match="CLICKHOUSE_AGENT_PASSWORD"):
        agent_client({})
