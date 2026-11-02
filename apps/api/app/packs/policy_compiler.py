"""Compile ``policies.yaml`` into ClickHouse access control (DECISIONS §9).

ClickHouse is the real permission layer. This module checks the policy
expressions a pack author writes and turns the policies into the ClickHouse
objects that enforce them.
"""

from collections.abc import Iterable

import sqlglot
from sqlglot import exp

from app.data.forbidden_functions import forbidden_function

# Column of an aggregate-only view holding the number of rows in each group.
ROW_COUNT_COLUMN = "row_count"


def check_row_filter(text: str, columns: Iterable[str]) -> str | None:
    """Return why ``text`` is not a usable row filter over ``columns``, or None when it is."""
    try:
        node = sqlglot.parse_one(text, read="clickhouse", into=exp.Condition)
    except sqlglot.errors.ParseError:
        return "does not parse as one expression"
    if node.find(exp.Query, exp.Subquery):
        return "must not contain a subquery"
    if name := forbidden_function(node):
        return f"function {name}() is not allowed"
    if node.find(exp.AggFunc):
        return "must not use an aggregate function"
    if not isinstance(node.unnest(), (exp.Predicate, exp.Connector, exp.Not, exp.Boolean)):
        return "must be a boolean condition such as a comparison"
    known = set(columns)
    for column in node.find_all(exp.Column):
        if column.table or column.name not in known:
            return f"unknown column '{column.sql(dialect='clickhouse')}'"
    return None
