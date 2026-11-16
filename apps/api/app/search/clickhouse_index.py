"""Pack search in ClickHouse (DECISIONS §5 Search collections).

Generation ``N`` of a logical collection ``<pack>_<index>`` is the table
``search.<collection>__<N>``: one row per point with the pack document's
payload as JSON, ``allowed_roles`` and ``document_id`` as columns, the dense
vector and each sparse vector as parallel term and weight arrays.
``search.live`` names the live generation of every collection; a compile
switches all collections of a pack with one insert, which ClickHouse writes
atomically, and the latest row of a collection wins.

``query`` scores exactly, without a vector index, over the rows readable by
any of the roles:

- dense: cosine similarity to the query vector;
- BM25 and character trigrams: the sum over the query's distinct terms of the
  document's term weight (``app.search.sparse``) times the term's inverse
  document frequency ``ln(1 + (N - n + 0.5) / (n + 0.5))`` over the whole
  generation, the formula of Qdrant's ``idf`` modifier, read at query time so
  documents uploaded after the compile count too;

and fuses the ranked lists with reciprocal rank fusion, each hit scoring
``1 / (RRF_K + position)`` per list from position 0, as Qdrant does. Ties keep
the lower point id first, so the order is deterministic.
"""

from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, datetime
import json
import os
import re

import clickhouse_connect

from app.search import sparse
from app.search.engine import BM25, DENSE, TRIGRAM, SearchError, prefetch_limit, uses_trigrams

DATABASE = "search"
LIVE_TABLE = f"{DATABASE}.live"
# Qdrant's reciprocal rank fusion constant, so both engines rank alike.
RRF_K = 2
INSERT_BATCH = 1000
COLUMNS = (
    "id", "document_id", "allowed_roles", "payload", "dense",
    "bm25_terms", "bm25_weights", "trigram_terms", "trigram_weights",
)
_COLLECTION = re.compile(r"[A-Za-z0-9_]+")
_SPARSE = {BM25: "bm25", TRIGRAM: "trigram"}


def search_client(env: Mapping[str, str] | None = None):
    """A ClickHouse client as ``search_index``, the only user of the search database."""
    env = os.environ if env is None else env
    password = env.get("CLICKHOUSE_SEARCH_PASSWORD", "")
    if not password:
        raise RuntimeError("CLICKHOUSE_SEARCH_PASSWORD must be set")
    return clickhouse_connect.get_client(
        host=env.get("CLICKHOUSE_HOST", "clickhouse"), port=int(env.get("CLICKHOUSE_HTTP_PORT", "8123")),
        username="search_index", password=password,
        # Shared across concurrent requests: a session would serialize them and refuse overlaps.
        autogenerate_session_id=False,
    )


def generation_table(collection: str, generation: int) -> str:
    """The unquoted table name, within the search database, of one generation."""
    if not _COLLECTION.fullmatch(collection):
        raise SearchError(f"invalid collection name {collection!r}")
    return f"{collection}__{int(generation)}"


def table_name(collection: str, generation: int) -> str:
    return f"{DATABASE}.`{generation_table(collection, generation)}`"


def fuse(ranked_lists: Iterable[Sequence[str]], size: int) -> list[tuple[str, float]]:
    """``(point id, score)`` of the best ``size`` points of several ranked lists by reciprocal rank fusion."""
    scores: dict[str, float] = {}
    for ranked in ranked_lists:
        for position, point in enumerate(ranked):
            scores[point] = scores.get(point, 0.0) + 1.0 / (RRF_K + position)
    return sorted(scores.items(), key=lambda item: (-item[1], item[0]))[:size]


def _dense_branch(table: str) -> str:
    return (
        f"SELECT '{DENSE}' AS list, id, payload, allowed_roles, "
        "toFloat64(1 - cosineDistance(dense, {vector:Array(Float32)})) AS score "
        f"FROM {table} WHERE hasAny(allowed_roles, {{roles:Array(String)}}) "
        "ORDER BY score DESC, id LIMIT {limit:UInt32}"
    )


def _sparse_branch(table: str, name: str) -> str:
    column = _SPARSE[name]
    terms = f"{{{column}:Array(UInt32)}}"
    return (
        # An aggregate over any table returns one row, so neither scalar is ever null.
        f"WITH assumeNotNull((SELECT count() FROM {table})) AS total, "
        f"assumeNotNull((SELECT sumForEach(arrayMap(term -> toUInt64(has({column}_terms, term)), {terms})) "
        f"FROM {table})) AS found, "
        "arrayMap(n -> log(1 + (total - n + 0.5) / (n + 0.5)), found) AS idf "
        f"SELECT '{name}' AS list, id, payload, allowed_roles, "
        f"arraySum((term, weight) -> weight * arrayElement(idf, indexOf({terms}, term)), "
        f"{column}_terms, {column}_weights) AS score "
        f"FROM {table} WHERE hasAny({column}_terms, {terms}) AND hasAny(allowed_roles, {{roles:Array(String)}}) "
        "ORDER BY score DESC, id LIMIT {limit:UInt32}"
    )


def search_statement(table: str, lists: Sequence[str]) -> str:
    """One query returning every ranked list of ``lists`` as ``(list, id, payload, allowed_roles, score)`` rows."""
    branches = [_dense_branch(table) if name == DENSE else _sparse_branch(table, name) for name in lists]
    return " UNION ALL ".join(f"SELECT * FROM ({branch})" for branch in branches)


def _row(point: dict) -> list:
    payload = {key: value for key, value in point["payload"].items() if key != "allowed_roles"}
    vectors = point["vector"]
    bm25 = vectors.get(BM25) or {"indices": [], "values": []}
    trigram = vectors.get(TRIGRAM) or {"indices": [], "values": []}
    return [
        point["id"], str(payload.get("document_id", "")), list(point["payload"].get("allowed_roles", [])),
        json.dumps(payload, ensure_ascii=False), [float(value) for value in vectors[DENSE]],
        list(bm25["indices"]), list(bm25["values"]), list(trigram["indices"]), list(trigram["values"]),
    ]


def _payload(text: str, roles: Sequence[str]) -> dict:
    return {**json.loads(text), "allowed_roles": list(roles)}


class ClickHouseSearch:
    def __init__(self, client):
        self._client = client

    def _run(self, call, *args, **kwargs):
        try:
            return call(*args, **kwargs)
        except SearchError:
            raise
        except Exception as error:  # noqa: BLE001 - every driver and server failure becomes a SearchError
            message = " ".join(str(error).split())[:300] or type(error).__name__
            raise SearchError(f"ClickHouse search failed: {message}") from error

    def _rows(self, sql: str, parameters: dict | None = None) -> list[tuple]:
        return self._run(lambda: self._client.query(sql, parameters=parameters or {}).result_rows)

    def _command(self, sql: str, parameters: dict | None = None) -> None:
        self._run(self._client.command, sql, parameters=parameters or {})

    # generations

    def generations(self, collection: str) -> list[int]:
        table_name(collection, 0)
        rows = self._rows(
            "SELECT name FROM system.tables WHERE database = {database:String} AND startsWith(name, {prefix:String})",
            {"database": DATABASE, "prefix": f"{collection}__"},
        )
        pattern = re.compile(rf"{re.escape(collection)}__(\d+)")
        return sorted(int(match.group(1)) for (name,) in rows if (match := pattern.fullmatch(name)))

    def live(self) -> dict[str, int]:
        rows = self._rows(f"SELECT collection, argMax(generation, switched_at) FROM {LIVE_TABLE} GROUP BY collection")
        return {collection: int(generation) for collection, generation in rows}

    def _live_generation(self, collection: str) -> int:
        rows = self._rows(
            f"SELECT argMax(generation, switched_at) FROM {LIVE_TABLE} WHERE collection = {{collection:String}} "
            "GROUP BY collection",
            {"collection": collection},
        )
        if not rows:
            raise SearchError(f"collection {collection} has no live generation")
        return int(rows[0][0])

    def _live_table(self, collection: str) -> str:
        return table_name(collection, self._live_generation(collection))

    def create(self, collection: str, generation: int, dimensions: int) -> None:
        self._command(
            f"CREATE TABLE {table_name(collection, generation)} ("
            "id String, document_id String, allowed_roles Array(String), payload String, dense Array(Float32), "
            "bm25_terms Array(UInt32), bm25_weights Array(Float32), "
            "trigram_terms Array(UInt32), trigram_weights Array(Float32), "
            f"CONSTRAINT dense_dimensions CHECK length(dense) = {int(dimensions)}"
            ") ENGINE = MergeTree ORDER BY id"
        )

    def drop(self, collection: str, generation: int) -> None:
        self._command(f"DROP TABLE IF EXISTS {table_name(collection, generation)}")

    def write(self, collection: str, points: Iterable[dict], generation: int | None = None) -> int:
        table = generation_table(collection, self._live_generation(collection) if generation is None else generation)
        count = 0
        batch: list[list] = []
        for point in points:
            batch.append(_row(point))
            if len(batch) == INSERT_BATCH:
                count += self._insert(table, batch)
                batch = []
        if batch:
            count += self._insert(table, batch)
        return count

    def _insert(self, table: str, rows: list[list]) -> int:
        self._run(self._client.insert, table, rows, column_names=list(COLUMNS), database=DATABASE)
        return len(rows)

    def size(self, collection: str, generation: int) -> int:
        return int(self._rows(f"SELECT count() FROM {table_name(collection, generation)}")[0][0])

    def switch_live(self, generations: Mapping[str, int]) -> None:
        for collection, generation in generations.items():
            table_name(collection, generation)
        now = datetime.now(UTC)
        rows = [[collection, int(generation), now] for collection, generation in generations.items()]
        self._run(self._client.insert, "live", rows, column_names=["collection", "generation", "switched_at"], database=DATABASE)

    # company documents

    def live_points(self, collection: str, document_id: str | None = None, with_vectors: bool = False) -> list[dict]:
        vectors = ", dense, bm25_terms, bm25_weights, trigram_terms, trigram_weights" if with_vectors else ""
        where = " WHERE document_id = {document:String}" if document_id else ""
        rows = self._rows(
            f"SELECT id, payload, allowed_roles{vectors} FROM {self._live_table(collection)}{where} ORDER BY id",
            {"document": document_id} if document_id else None,
        )
        points = []
        for row in rows:
            point = {"id": row[0], "payload": _payload(row[1], row[2])}
            if with_vectors:
                point["vector"] = {
                    DENSE: list(row[3]), BM25: {"indices": list(row[4]), "values": list(row[5])},
                    **({TRIGRAM: {"indices": list(row[6]), "values": list(row[7])}} if row[6] else {}),
                }
            points.append(point)
        return points

    def delete_document(self, collection: str, document_id: str) -> None:
        self._command(
            f"DELETE FROM {self._live_table(collection)} WHERE document_id = {{document:String}}",
            {"document": document_id},
        )

    def set_document_roles(self, collection: str, document_id: str, roles: Sequence[str]) -> None:
        self._command(
            f"ALTER TABLE {self._live_table(collection)} UPDATE allowed_roles = {{roles:Array(String)}} "
            "WHERE document_id = {document:String} SETTINGS mutations_sync = 2",
            {"roles": list(roles), "document": document_id},
        )

    # search

    def query(self, collection: str, text: str, vector: Sequence[float], roles: Sequence[str], size: int) -> list[dict]:
        parameters: dict = {"vector": [float(value) for value in vector], "roles": list(roles), "limit": prefetch_limit(size)}
        lists = [DENSE]
        words = sparse.query_vector(sparse.terms(text))["indices"]
        if words:
            lists.append(BM25)
            parameters["bm25"] = words
        grams = sparse.query_vector(sparse.trigrams(text))["indices"]
        if uses_trigrams(collection) and grams:
            lists.append(TRIGRAM)
            parameters["trigram"] = grams
        rows = self._rows(search_statement(self._live_table(collection), lists), parameters)
        ranked: dict[str, list[str]] = {name: [] for name in lists}
        sources: dict[str, dict] = {}
        for name, point, payload, allowed, _score in sorted(rows, key=lambda row: (row[0], -row[4], row[1])):
            ranked[name].append(point)
            sources.setdefault(point, _payload(payload, allowed))
        return [
            {"id": sources[point]["id"], "score": score, "source": sources[point]}
            for point, score in fuse(ranked.values(), size)
        ]
