"""Check generated SQL before it reaches ClickHouse (DECISIONS §6 step 10).

The guard is the second of three permission layers: it rejects early with an
understandable message, while ClickHouse grants remain the real security
layer. It parses the SQL with sqlglot and accepts exactly one read query
(``SELECT``, set operations and CTEs) over allowlisted ``marts`` tables and
columns, without table functions, external-access or blocking functions,
``system`` tables, or ``SETTINGS``/``FORMAT`` clauses. Every rejection is a
``policy`` error; SQL that does not parse is an ``sql`` error, so it is
retried instead of executed.

The SQL text is executed as generated: re-rendering it through sqlglot can
change ClickHouse functions, so the guard only adds or caps the outer LIMIT.
Columns are checked per SELECT scope: a qualified column against its own
table or subquery, an unqualified one against the scope's tables and
subqueries or an alias the scope defines (in the select list, only aliases
defined before it). ClickHouse grants remain the final column check.
"""

from collections.abc import Mapping
from dataclasses import dataclass

import sqlglot
from sqlglot import exp
from sqlglot.optimizer.scope import Scope, traverse_scope

from app.agent.errors import AgentError
from app.agent.state import AgentDeps, AgentState, record_error
from app.contracts.result import MAX_RESULT_ROWS
from app.data.clickhouse import MARTS_DATABASE

NODE = "guard"
# system tables a query may read; none are needed yet.
SYSTEM_TABLE_WHITELIST: frozenset[str] = frozenset()
FORBIDDEN_FUNCTIONS = frozenset(name.lower() for name in (
    # table functions and external access
    "file", "url", "urlCluster", "remote", "remoteSecure", "s3", "s3Cluster", "gcs", "azureBlobStorage",
    "azureBlobStorageCluster", "hdfs", "hdfsCluster", "mysql", "postgresql", "mongodb", "redis", "sqlite",
    "jdbc", "odbc", "executable", "input", "cluster", "clusterAllReplicas", "merge", "view", "dictionary",
    "generateRandom", "numbers", "numbers_mt", "zeros", "zeros_mt", "values", "format", "null", "iceberg",
    "deltaLake", "hudi", "loop", "fuzzJSON",
    # column matchers that bypass the column allowlist
    "columns",
    # reads outside the query's tables
    "joinGet", "joinGetOrNull",
    # deliberate stalls
    "sleep", "sleepEachRow",
))
FORBIDDEN_PREFIXES = ("dictget", "dicthas", "dictis")


@dataclass(frozen=True)
class Allowlist:
    """``marts`` tables a query may read, each with the columns it may use."""

    tables: Mapping[str, frozenset[str]]


@dataclass(frozen=True)
class GuardResult:
    sql: str | None = None
    error: AgentError | None = None


class _Rejected(Exception):
    pass


def _policy(message: str) -> GuardResult:
    return GuardResult(error=AgentError("policy", NODE, message))


def _function_name(node: exp.Func) -> str:
    return (node.name if isinstance(node, exp.Anonymous) else node.sql_name()).lower()


def _check_functions(tree: exp.Expression) -> None:
    for node in tree.find_all(exp.Func):
        name = _function_name(node)
        if name in FORBIDDEN_FUNCTIONS or name.startswith(FORBIDDEN_PREFIXES):
            raise _Rejected(f"function {name}() is not allowed")


def _base_tables(scopes: list[Scope]) -> list[exp.Table]:
    """Table nodes that some scope reads as a real table; CTE references resolve to scopes instead."""
    return [source for scope in scopes for source in scope.sources.values() if isinstance(source, exp.Table)]


def _check_tables(tree: exp.Expression, allowlist: Allowlist, scopes: list[Scope]) -> set[str]:
    """Return the allowlisted base tables the query reads.

    Whether a name means a CTE or a table is decided by each query's own
    scope, so a CTE defined in a subquery cannot hide an outer table.
    """
    base = {id(table) for table in _base_tables(scopes)}
    tables: set[str] = set()
    for table in tree.find_all(exp.Table):
        if not isinstance(table.this, exp.Identifier):
            name = _function_name(table.this) if isinstance(table.this, exp.Func) else table.this.sql()
            raise _Rejected(f"table function {name}() is not allowed")
        if table.catalog:
            raise _Rejected(f"table {table.sql(dialect='clickhouse')} is not allowed")
        if table.db == "system" and table.name in SYSTEM_TABLE_WHITELIST:
            continue
        if table.db == "system":
            raise _Rejected(f"system table system.{table.name} is not allowed")
        if id(table) not in base and not table.db:
            continue  # a CTE reference
        if table.db not in ("", MARTS_DATABASE) or table.name not in allowlist.tables:
            raise _Rejected(f"table {table.sql(dialect='clickhouse')} is not an approved dataset")
        tables.add(table.name)
    return tables


def _visible_aliases(column: exp.Column, select: exp.Expression) -> set[str]:
    """Aliases of ``select`` that ``column`` may refer to."""
    if not isinstance(select, exp.Select):
        return set()
    projections = select.expressions
    node: exp.Expression | None = column
    while node is not None and node.parent is not select:
        node = node.parent
    if node is not None and any(node is projection for projection in projections):
        position = next(index for index, projection in enumerate(projections) if projection is node)
        projections = projections[:position]
    return {projection.alias for projection in projections if isinstance(projection, exp.Alias)}


def _source_columns(scope: Scope, allowlist: Allowlist) -> dict[str, set[str]]:
    """Columns each source name of ``scope`` exposes, including the enclosing scopes' sources.

    A correlated subquery may refer to an outer query's tables; the scope's own
    sources shadow outer ones with the same name.
    """
    columns_of: dict[str, set[str]] = {}
    current: Scope | None = scope
    while current is not None:
        for name, source in current.sources.items():
            if name in columns_of:
                continue
            if isinstance(source, exp.Table):
                columns_of[name] = set(allowlist.tables.get(source.name, frozenset()))
            else:
                columns_of[name] = set(source.expression.named_selects)
        current = current.parent
    return columns_of


def _check_scope_columns(scope: Scope, allowlist: Allowlist) -> None:
    columns_of = _source_columns(scope, allowlist)
    unqualified = set().union(*columns_of.values())
    for column in scope.columns:
        if isinstance(column.this, exp.Star):
            continue
        if column.table:
            if column.table not in columns_of:
                raise _Rejected(f"column {column.sql(dialect='clickhouse')} refers to an unknown table")
            if column.name not in columns_of[column.table]:
                raise _Rejected(f"column {column.name} is not an approved column of {column.table}")
        elif column.name not in unqualified and column.name not in _visible_aliases(column, scope.expression):
            raise _Rejected(f"column {column.name} is not an approved column of the tables it reads")


def _check_columns(scopes: list[Scope], allowlist: Allowlist) -> None:
    for scope in scopes:
        _check_scope_columns(scope, allowlist)


def _is_projection(node: exp.Expression) -> bool:
    return isinstance(node.parent, exp.Select) and any(node is projection for projection in node.parent.expressions)


def _check_stars(tree: exp.Expression, scopes: list[Scope]) -> None:
    """``*`` outside ``count(*)`` or over a base table could return columns outside the allowlist."""
    for star in tree.find_all(exp.Star):
        qualified = star.parent if isinstance(star.parent, exp.Column) else star
        if not isinstance(star.parent, exp.Count) and not _is_projection(qualified):
            raise _Rejected("* is allowed only in count(*) or a select list; name the columns")
    for scope in scopes:
        select = scope.expression
        if not isinstance(select, exp.Select):
            continue
        for projection in select.expressions:
            if isinstance(projection, exp.Star):
                # An unqualified * reads every selected source.
                sources = [source for _, source in scope.selected_sources.values()]
            elif isinstance(projection, exp.Column) and isinstance(projection.this, exp.Star):
                sources = [scope.sources.get(projection.table)]
            else:
                continue
            if any(isinstance(source, exp.Table) for source in sources):
                raise _Rejected("SELECT * is not allowed on a dataset; name the columns")


def _check_clauses(tree: exp.Expression) -> None:
    for node in tree.walk():
        if node.args.get("settings"):
            raise _Rejected("SETTINGS clauses are not allowed")
        if node.args.get("format"):
            raise _Rejected("FORMAT clauses are not allowed")


def _limited(sql: str, tree: exp.Query, max_rows: int) -> str:
    """Return SQL whose outer result has at most ``max_rows`` rows."""
    body = sql.strip().rstrip(";").rstrip()
    limit = tree.args.get("limit")
    value = limit.expression if isinstance(limit, exp.Limit) and not limit.expressions else None
    if isinstance(value, exp.Literal) and value.is_int and int(value.this) <= max_rows:
        return body
    if limit is None and isinstance(tree, exp.Select):
        return f"{body}\nLIMIT {max_rows}"
    return f"SELECT * FROM (\n{body}\n) LIMIT {max_rows}"


def guard_sql(sql: str, allowlist: Allowlist, max_rows: int) -> GuardResult:
    """Return the SQL to run, with its outer LIMIT capped at ``max_rows``, or a classified error."""
    try:
        statements = [statement for statement in sqlglot.parse(sql, read="clickhouse") if statement is not None]
    except sqlglot.errors.SqlglotError as error:  # parse and tokenizer errors alike
        first = " ".join(str(error).split())[:300]
        return GuardResult(error=AgentError("sql", NODE, f"SQL does not parse: {first}"))
    if len(statements) != 1:
        return _policy(f"exactly one statement is allowed, got {len(statements)}")
    tree = statements[0]
    if not isinstance(tree, exp.Query):
        return _policy(f"only SELECT queries are allowed, got {tree.key.upper()}")
    try:
        _check_clauses(tree)
        scopes = traverse_scope(tree)
        tables = _check_tables(tree, allowlist, scopes)
        _check_functions(tree)
        if not tables:
            raise _Rejected("the query reads no approved dataset")
        _check_stars(tree, scopes)
        _check_columns(scopes, allowlist)
    except _Rejected as rejection:
        return _policy(str(rejection))
    except sqlglot.errors.OptimizeError as error:  # for example two sources with the same alias
        return GuardResult(error=AgentError("sql", NODE, f"SQL cannot be resolved: {' '.join(str(error).split())[:300]}"))
    return GuardResult(sql=_limited(sql, tree, max_rows))


def allowlist_for(pack) -> Allowlist:
    """Phase 3 allowlist: every column of every approved dataset."""
    return Allowlist({dataset.id: frozenset(column.name for column in dataset.columns) for dataset in pack.datasets.datasets})


def guard(state: AgentState, deps: AgentDeps) -> dict:
    """Graph node. The cap is one row above the result limit, so shape_result can tell a result was cut."""
    result = guard_sql(state["sql"], allowlist_for(deps.compiled.pack), MAX_RESULT_ROWS + 1)
    if result.error is not None:
        return {**record_error(state, result.error), "sql": state["sql"]}
    attempts = list(state["attempts"])
    attempts[-1] = attempts[-1].model_copy(update={"sql": result.sql})
    return {"sql": result.sql, "attempts": attempts}
