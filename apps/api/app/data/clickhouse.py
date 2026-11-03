"""Run agent queries on ClickHouse as the ClickHouse user of the asking role.

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
from app.config import positive_int
from app.packs.policy_compiler import Names, agent_password

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
        """Limits from ``QUERY_MAX_*``; each must be positive, since 0 would mean unlimited."""
        env = os.environ if env is None else env
        defaults = cls()
        return cls(
            max_execution_time=positive_int(env, "QUERY_MAX_EXECUTION_TIME", defaults.max_execution_time),
            max_result_rows=positive_int(env, "QUERY_MAX_RESULT_ROWS", defaults.max_result_rows),
            max_memory_usage=positive_int(env, "QUERY_MAX_MEMORY_USAGE", defaults.max_memory_usage),
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

    def _settings(self, trace_id: str, query_id: str) -> dict:
        return {
            "max_execution_time": self._limits.max_execution_time,
            "max_result_rows": self._limits.max_result_rows,
            "max_memory_usage": self._limits.max_memory_usage,
            "log_comment": trace_id,
            "query_id": query_id,
        }

    def _query(self, sql: str, trace_id: str) -> QueryOutput:
        """Run one query and read its whole result; any failure, including while reading rows, is a QueryError."""
        query_id = self._new_query_id()
        try:
            result = self._client.query(sql, settings=self._settings(trace_id, query_id))
            return QueryOutput(
                query_id=query_id,
                columns=list(result.column_names),
                types=[column_type.name for column_type in result.column_types],
                rows=[tuple(row) for row in result.result_rows],
            )
        except Exception as error:  # noqa: BLE001 - every driver failure is classified, never raised raw
            category, code = classify(error)
            raise QueryError(category, _message(error), query_id, code) from error

    def explain(self, sql: str, trace_id: str) -> str:
        """Run ``EXPLAIN`` on the query; return the EXPLAIN query's id."""
        return self._query(f"EXPLAIN {sql}", trace_id).query_id

    def run(self, sql: str, trace_id: str) -> QueryOutput:
        output = self._query(sql, trace_id)
        if output.columns:
            return output
        # An empty result arrives without column metadata; DESCRIBE reads it without running the query.
        # The newline ends a trailing line comment. The column list has one row per column, far below
        # the row limit, which the agent user cannot lift anyway.
        described = self._query(f"DESCRIBE TABLE (\n{sql}\n)", trace_id)
        return QueryOutput(
            query_id=output.query_id,
            columns=[row[0] for row in described.rows],
            types=[row[1] for row in described.rows],
            rows=output.rows,
        )


class QueryStopper:
    """Stops a running agent query by its id and user.

    ``KILL QUERY WHERE`` reads ``system.processes``, which lists every user's
    running SQL, so the role users cannot run it; ``agent_query_stopper`` may
    only list and stop queries.
    """

    def __init__(self, client):
        self._client = client

    def stop(self, query_id: str, user: str) -> None:
        self._client.command(
            "KILL QUERY WHERE query_id = {query_id:String} AND user = {user:String} ASYNC",
            parameters={"query_id": query_id, "user": user},
        )


def stopper_client(env: Mapping[str, str] | None = None):
    env = os.environ if env is None else env
    password = env.get("CLICKHOUSE_QUERY_STOPPER_PASSWORD", "")
    if not password:
        raise RuntimeError("CLICKHOUSE_QUERY_STOPPER_PASSWORD must be set")
    return clickhouse_connect.get_client(
        host=env.get("CLICKHOUSE_HOST", "clickhouse"),
        port=int(env.get("CLICKHOUSE_HTTP_PORT", "8123")),
        username="agent_query_stopper",
        password=password,
        autogenerate_session_id=False,
    )


def agent_client(pack: str, role: str, env: Mapping[str, str] | None = None):
    """Client for the role's read-only user that compile_pack created; the admin credentials are never used here.

    The password is derived from ``CLICKHOUSE_AGENT_PASSWORD`` the way compile_pack derived it.
    """
    env = os.environ if env is None else env
    secret = env.get("CLICKHOUSE_AGENT_PASSWORD", "")
    if not secret:
        raise RuntimeError("CLICKHOUSE_AGENT_PASSWORD must be set")
    user = Names(pack).user(role)
    return clickhouse_connect.get_client(
        host=env.get("CLICKHOUSE_HOST", "clickhouse"),
        port=int(env.get("CLICKHOUSE_HTTP_PORT", "8123")),
        username=user,
        password=agent_password(secret, user),
        database=MARTS_DATABASE,
        # Every setting travels with its query, so no session is needed; one would let a query that
        # outlives its caller (a timed-out eval case) lock the client for the next query.
        autogenerate_session_id=False,
    )
