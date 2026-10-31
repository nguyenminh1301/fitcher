"""Run agent queries on ClickHouse as the read-only agent user.

Every query carries the resource limits, ``log_comment = trace_id`` (so
``system.query_log`` joins the run's trace) and a generated ``query_id``.
Driver errors are classified for the check node: resource and connection
failures are ``runtime``, access violations are ``policy`` and everything else
is ``sql``, which the generator may repair.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
import os
import re
from uuid import uuid4

import clickhouse_connect

from app.agent.errors import ErrorCategory

DEFAULT_AGENT_USER = "agent_readonly"
# The only database the agent reads (DECISIONS §4); also its connection default.
MARTS_DATABASE = "marts"

# ClickHouse error codes for queries that were valid but could not finish.
RUNTIME_CODES = frozenset({
    158,  # TOO_MANY_ROWS
    159,  # TIMEOUT_EXCEEDED
    160,  # TOO_SLOW
    173,  # CANNOT_ALLOCATE_MEMORY
    202,  # TOO_MANY_SIMULTANEOUS_QUERIES
    209,  # SOCKET_TIMEOUT
    210,  # NETWORK_ERROR
    241,  # MEMORY_LIMIT_EXCEEDED
    307,  # TOO_MANY_BYTES
    394,  # QUERY_WAS_CANCELLED
    396,  # TOO_MANY_ROWS_OR_BYTES
})
# Error codes for queries the agent user is not permitted to run.
POLICY_CODES = frozenset({
    164,  # READONLY
    452,  # SETTING_CONSTRAINT_VIOLATION
    497,  # ACCESS_DENIED
})
_CODE = re.compile(r"Code: (\d+)\.")
MESSAGE_LIMIT = 1000


@dataclass(frozen=True)
class QueryLimits:
    max_execution_time: int = 30
    max_result_rows: int = 10_000
    max_memory_usage: int = 2_000_000_000

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "QueryLimits":
        env = os.environ if env is None else env
        defaults = cls()
        return cls(
            max_execution_time=int(env.get("QUERY_MAX_EXECUTION_TIME") or defaults.max_execution_time),
            max_result_rows=int(env.get("QUERY_MAX_RESULT_ROWS") or defaults.max_result_rows),
            max_memory_usage=int(env.get("QUERY_MAX_MEMORY_USAGE") or defaults.max_memory_usage),
        )


@dataclass(frozen=True)
class QueryOutput:
    query_id: str
    columns: list[str]
    types: list[str]
    rows: list[tuple]


class QueryError(Exception):
    def __init__(self, category: ErrorCategory, message: str, query_id: str, code: int | None = None):
        super().__init__(message)
        self.category = category
        self.message = message
        self.query_id = query_id
        self.code = code


def classify(error: BaseException) -> tuple[ErrorCategory, int | None]:
    """Category and ClickHouse error code of a driver exception."""
    match = _CODE.search(str(error))
    if match is None:
        return "runtime", None
    code = int(match.group(1))
    if code in RUNTIME_CODES:
        return "runtime", code
    if code in POLICY_CODES:
        return "policy", code
    return "sql", code


def _message(error: BaseException) -> str:
    """The ClickHouse exception text without the driver's wrapper and URL."""
    text = " ".join(str(error).split())
    start = text.find("Code: ")
    if start >= 0:
        text = text[start:]
    return re.sub(r"\s*\(for url [^)]*\)", "", text)[:MESSAGE_LIMIT]


class ClickHouseRunner:
    def __init__(self, client, limits: QueryLimits, new_query_id: Callable[[], str] = lambda: str(uuid4())):
        self._client = client
        self._limits = limits
        self._new_query_id = new_query_id

    def _settings(self, trace_id: str, query_id: str, max_result_rows: int | None) -> dict:
        return {
            "max_execution_time": self._limits.max_execution_time,
            "max_result_rows": self._limits.max_result_rows if max_result_rows is None else max_result_rows,
            "max_memory_usage": self._limits.max_memory_usage,
            "log_comment": trace_id,
            "query_id": query_id,
        }

    def _query(self, sql: str, trace_id: str, max_result_rows: int | None = None):
        query_id = self._new_query_id()
        try:
            return query_id, self._client.query(sql, settings=self._settings(trace_id, query_id, max_result_rows))
        except Exception as error:  # noqa: BLE001 - every driver failure is classified, never raised raw
            category, code = classify(error)
            raise QueryError(category, _message(error), query_id, code) from error

    def explain(self, sql: str, trace_id: str) -> str:
        """Run ``EXPLAIN`` on the query; return the EXPLAIN query's id."""
        query_id, _ = self._query(f"EXPLAIN {sql}", trace_id)
        return query_id

    def run(self, sql: str, trace_id: str) -> QueryOutput:
        query_id, result = self._query(sql, trace_id)
        columns = list(result.column_names)
        types = [column_type.name for column_type in result.column_types]
        if not columns:
            # An empty result arrives without column metadata; DESCRIBE reads it without running the query.
            # The newline ends a trailing line comment, and 0 lifts the row limit for the column list.
            _, described = self._query(f"DESCRIBE TABLE (\n{sql}\n)", trace_id, max_result_rows=0)
            columns = [row[0] for row in described.result_rows]
            types = [row[1] for row in described.result_rows]
        return QueryOutput(query_id=query_id, columns=columns, types=types, rows=[tuple(row) for row in result.result_rows])


def agent_client(env: Mapping[str, str] | None = None):
    """Client for the read-only agent user; the admin credentials are never used here."""
    env = os.environ if env is None else env
    password = env.get("CLICKHOUSE_AGENT_PASSWORD", "")
    if not password:
        raise RuntimeError("CLICKHOUSE_AGENT_PASSWORD must be set")
    return clickhouse_connect.get_client(
        host=env.get("CLICKHOUSE_HOST", "clickhouse"),
        port=int(env.get("CLICKHOUSE_HTTP_PORT", "8123")),
        username=env.get("CLICKHOUSE_AGENT_USER") or DEFAULT_AGENT_USER,
        password=password,
        database=MARTS_DATABASE,
    )
