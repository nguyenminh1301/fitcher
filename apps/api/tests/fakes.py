"""In-memory stand-ins for ClickHouse, OpenSearch and the embedding alias.

They record every call so tests can assert ordering, and each can be told to
fail at a chosen point.
"""

from collections.abc import Iterable, Sequence
from datetime import date
import fnmatch
import re

from app.search.opensearch import SearchError


class FakeWarehouse:
    """Answers the compiler's queries from a table -> columns mapping; records access-control commands.

    ``coverage`` maps a table to ``(rows, min_date, max_date)``; ``values`` maps
    ``(table, column)`` to ``[(value, count)]``; ``failures`` maps a substring of
    the SQL to the error raised for any query containing it.
    """

    def __init__(
        self,
        tables: dict[str, set[str]],
        coverage: dict[str, tuple[int, date, date]] | None = None,
        values: dict[tuple[str, str], list[tuple[str, int]]] | None = None,
        failures: dict[str, str] | None = None,
    ):
        self.tables = tables
        self.coverage = coverage or {}
        self.values = values or {}
        self.failures = failures or {}
        self.queries: list[tuple[str, dict | None]] = []
        # Access-control DDL, and every query and command in the order they arrived.
        self.commands: list[str] = []
        self.log: list[str] = []

    def command(self, sql: str) -> None:
        self.commands.append(sql)
        self.log.append(sql)

    def query(self, sql: str, settings: dict | None = None) -> list[tuple]:
        self.queries.append((sql, settings))
        self.log.append(sql)
        for fragment, message in self.failures.items():
            if fragment in sql:
                raise RuntimeError(message)
        if "system.columns" in sql:
            return [(table, column) for table, columns in self.tables.items() for column in sorted(columns)]
        if "FROM system." in sql:
            return []  # a cluster without managed access objects
        table = re.search(r"FROM `marts`\.`(\w+)`", sql).group(1)
        if sql.startswith("SELECT count(), min("):
            return [self.coverage.get(table, (0, date(1970, 1, 1), date(1970, 1, 1)))]
        if "toString(" in sql:
            column = re.search(r"toString\(`(\w+)`\)", sql).group(1)
            return self.values.get((table, column), [])
        return [(1,)]


class FakeEmbeddings:
    """Deterministic vectors; ``fail_after`` raises once that many texts were embedded."""

    def __init__(self, dimensions: int = 4, fail_after: int | None = None):
        self.dimensions = dimensions
        self.fail_after = fail_after
        self.calls: list[list[str]] = []

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        embedded = sum(len(call) for call in self.calls)
        if self.fail_after is not None and embedded + len(texts) > self.fail_after:
            raise RuntimeError("embedding service unavailable")
        self.calls.append(list(texts))
        return [[float(len(text) % 7), 1.0, 0.0, 0.5][: self.dimensions] for text in texts]


class FakeSearch:
    """In-memory OpenSearch: indices, documents, aliases and a call log.

    ``fail_bulk_into`` makes bulk indexing into any index whose name contains
    that substring fail; ``search_results`` maps an alias to the hits returned.
    """

    def __init__(self, fail_bulk_into: str | None = None, search_results=None):
        self.indices: dict[str, dict] = {}
        self.documents: dict[str, list[dict]] = {}
        self.aliases: dict[str, str] = {}
        self.pipelines: dict[str, dict] = {}
        self.alias_updates: list[list[dict]] = []
        self.searches: list[tuple[str, dict, str | None]] = []
        self.fail_bulk_into = fail_bulk_into
        self.search_results = search_results or {}

    def put_search_pipeline(self, name: str, body: dict) -> None:
        self.pipelines[name] = body

    def create_index(self, name: str, body: dict) -> None:
        if name in self.indices:
            raise SearchError(f"index {name} already exists")
        self.indices[name] = body
        self.documents[name] = []

    def delete_index(self, name: str) -> None:
        self.indices.pop(name, None)
        self.documents.pop(name, None)
        self.aliases = {alias: index for alias, index in self.aliases.items() if index != name}

    def list_indices(self, pattern: str) -> list[str]:
        return sorted(name for name in self.indices if fnmatch.fnmatchcase(name, pattern))

    def alias_targets(self, pattern: str) -> dict[str, list[str]]:
        return {alias: [index] for alias, index in self.aliases.items() if fnmatch.fnmatchcase(alias, pattern)}

    def update_aliases(self, actions: list[dict]) -> None:
        self.alias_updates.append(actions)
        for action in actions:
            if "remove" in action:
                self.aliases.pop(action["remove"]["alias"], None)
            else:
                self.aliases[action["add"]["alias"]] = action["add"]["index"]

    def bulk_index(self, index: str, documents: Iterable[dict]) -> int:
        if self.fail_bulk_into and self.fail_bulk_into in index:
            raise SearchError(f"bulk indexing into {index} failed")
        documents = list(documents)
        self.documents[index].extend(documents)
        return len(documents)

    def refresh(self, index: str) -> None:
        pass

    def count(self, index: str) -> int:
        return len(self.documents[index])

    def search(self, index: str, body: dict, pipeline: str | None = None) -> list[dict]:
        self.searches.append((index, body, pipeline))
        if callable(self.search_results):
            return self.search_results(index, body)
        return self.search_results.get(index, [])


class FakeRunner:
    """Scripted ClickHouse runner: each EXPLAIN or run pops the next outcome.

    An outcome is a QueryError to raise or, for ``run``, a QueryOutput; EXPLAIN
    succeeds when its queue is empty.
    """

    def __init__(self, explains: list | None = None, runs: list | None = None):
        self.explains = list(explains or [])
        self.runs = list(runs or [])
        self.calls: list[tuple[str, str, str]] = []

    def explain(self, sql: str, trace_id: str) -> str:
        self.calls.append(("explain", sql, trace_id))
        outcome = self.explains.pop(0) if self.explains else None
        if isinstance(outcome, Exception):
            raise outcome
        return "explain-id"

    def run(self, sql: str, trace_id: str):
        self.calls.append(("run", sql, trace_id))
        outcome = self.runs.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class FakeLogWriter:
    """Collects agent log records.

    ``write_results`` scripts each ``write_now`` outcome in order, ``fail_tables``
    fails every ``write_now`` into those tables, and ``lost`` sets each flush's losses.
    """

    def __init__(self, write_results: Sequence[bool] = (), lost: int = 0, fail_tables: Iterable[str] = ()):
        self.written: list = []
        self.queued: list = []
        self.flushed: list[str] = []
        self.write_results = list(write_results)
        self.lost = lost
        self.fail_tables = set(fail_tables)

    def write_now(self, record) -> bool:
        self.written.append(record)
        if record.TABLE in self.fail_tables:
            return False
        return self.write_results.pop(0) if self.write_results else True

    def enqueue(self, record) -> bool:
        self.queued.append(record)
        return True

    def flush_trace(self, trace_id: str, timeout: float = 5.0):
        from app.observability.log_writer import FlushResult

        self.flushed.append(trace_id)
        count = sum(1 for record in self.queued if getattr(record, "trace_id", "") == trace_id)
        return FlushResult(written=count - self.lost, lost=self.lost)

    def close(self, timeout: float = 5.0) -> None:
        self.closed = True

    def runs(self) -> list:
        return [record for record in self.written if record.TABLE == "runs"]


class QueryResult:
    def __init__(self, rows: list[tuple]):
        self.result_rows = rows


class FakeConversationClient:
    """In-memory ``agent_logs`` conversation tables answering each query ``ConversationStore`` sends.

    ``FINAL`` reads keep the row with the latest ``updated_at`` per key, as a
    ReplacingMergeTree does. ``fail`` makes every call raise, as an unreachable
    ClickHouse would; ``naive_times`` returns times without a time zone, as
    clickhouse-connect returns ``DateTime64('UTC')`` values.
    """

    def __init__(self, fail: bool = False, naive_times: bool = False):
        self.fail = fail
        self.naive_times = naive_times
        self.tables: dict[str, list[dict]] = {"chat_messages": [], "conversations": [], "conversation_groups": [], "feedback": []}
        self.queries: list[str] = []

    def _check(self) -> None:
        if self.fail:
            raise ConnectionError("ClickHouse is unreachable")

    def insert(self, table, data, column_names, database):
        self._check()
        assert database == "agent_logs"
        self.tables[table] += [dict(zip(column_names, row)) for row in data]

    def _latest(self, table: str, key: str, user_id: str) -> list[dict]:
        latest: dict[str, dict] = {}
        for row in self.tables[table]:
            if row["user_id"] == user_id and (row[key] not in latest or row["updated_at"] >= latest[row[key]]["updated_at"]):
                latest[row[key]] = row
        return list(latest.values())

    def query(self, sql, parameters):
        result = self._answer(sql, parameters)
        if self.naive_times:
            result.result_rows = [
                tuple(value.replace(tzinfo=None) if hasattr(value, "tzinfo") and hasattr(value, "hour") else value for value in row)
                for row in result.result_rows
            ]
        return result

    def _answer(self, sql, parameters):
        from app.conversation import store

        self._check()
        self.queries.append(sql)
        user = parameters["user_id"]
        messages = [row for row in self.tables["chat_messages"] if row["user_id"] == user]
        if sql in (store.CONVERSATION_SQL, store.CONVERSATIONS_SQL):
            rows = self._latest("conversations", "conversation_id", user)
            if sql == store.CONVERSATION_SQL:
                rows = [row for row in rows if row["conversation_id"] == parameters["conversation_id"]]
            return QueryResult([tuple(row[column] for column in store.CONVERSATION_COLUMNS) for row in rows])
        if sql in (store.GROUP_SQL, store.GROUPS_SQL):
            rows = self._latest("conversation_groups", "group_id", user)
            if sql == store.GROUP_SQL:
                rows = [row for row in rows if row["group_id"] == parameters["group_id"]]
            return QueryResult([tuple(row[column] for column in store.GROUP_COLUMNS) for row in rows])
        if sql == store.MESSAGES_SQL:
            rows = sorted(
                (row for row in messages if row["conversation_id"] == parameters["conversation_id"]),
                key=lambda row: (row["turn"], row["revision"], row["ts"]),
            )
            return QueryResult([tuple(row.get(column, "") for column in store.MESSAGE_COLUMNS) for row in rows])
        if sql == store.ACTIVITY_SQL:
            last: dict[str, object] = {}
            for row in messages:
                last[row["conversation_id"]] = max(row["ts"], last.get(row["conversation_id"], row["ts"]))
            return QueryResult(list(last.items()))
        if sql == store.ANSWERS_SQL:
            return QueryResult([(sum(row["role"] == "assistant" and row["trace_id"] == parameters["trace_id"] for row in messages),)])
        assert sql == store.QUESTIONS_SQL, sql
        return QueryResult([(row["conversation_id"], row["content"]) for row in messages if row["role"] == "user"])


class FakeClassifier:
    """A screening classifier scoring each text by the first marker it contains; 0.0 otherwise."""

    version = "fake-guard@1"

    def __init__(self, marked: dict[str, float] | None = None):
        self.marked = marked or {}
        self.calls: list[list[str]] = []

    def scores(self, texts):
        self.calls.append(list(texts))
        return [next((score for marker, score in self.marked.items() if marker in text), 0.0) for text in texts]
