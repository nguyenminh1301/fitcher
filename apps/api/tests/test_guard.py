"""The SQL guard: one read query over allowlisted tables and columns, LIMIT enforced."""

import pytest

from app.agent.nodes.guard import Allowlist, guard_sql

ALLOWLIST = Allowlist({
    "widget_sales": frozenset({"sale_ref", "sold_on", "widget_name", "sale_amount"}),
    "widget_refunds": frozenset({"refund_ref", "refunded_on", "sale_ref", "refund_total"}),
})
MAX_ROWS = 5001

TOP_WIDGETS = """
WITH current AS (
    SELECT widget_name, sumIf(sale_amount, sold_on >= toDate('2025-01-01') AND sold_on < toDate('2025-04-01')) AS q1_2025,
           sumIf(sale_amount, sold_on >= toDate('2024-01-01') AND sold_on < toDate('2024-04-01')) AS q1_2024,
           q1_2025 - q1_2024 AS change
    FROM marts.widget_sales
    WHERE sold_on >= toDate('2024-01-01') AND sold_on < toDate('2025-04-01')
    GROUP BY widget_name
)
SELECT widget_name, q1_2025, q1_2024, change, round(change / nullIf(q1_2024, 0) * 100, 2) AS change_pct
FROM current
ORDER BY q1_2025 DESC, widget_name
LIMIT 10
"""


def accepted(sql: str) -> str:
    result = guard_sql(sql, ALLOWLIST, MAX_ROWS)
    assert result.error is None, result.error
    return result.sql


def rejected(sql: str):
    result = guard_sql(sql, ALLOWLIST, MAX_ROWS)
    assert result.sql is None
    return result.error


def test_cte_query_within_the_limit_runs_unchanged():
    assert accepted(TOP_WIDGETS) == TOP_WIDGETS.strip()


def test_join_with_table_aliases_is_accepted():
    sql = (
        "SELECT s.widget_name, sum(r.refund_total) AS refunded FROM marts.widget_refunds AS r "
        "JOIN marts.widget_sales AS s ON r.sale_ref = s.sale_ref GROUP BY s.widget_name ORDER BY refunded DESC LIMIT 5"
    )

    assert accepted(sql) == sql


def test_select_without_limit_gets_one_appended():
    assert accepted("SELECT widget_name FROM marts.widget_sales ORDER BY widget_name;") == (
        f"SELECT widget_name FROM marts.widget_sales ORDER BY widget_name\nLIMIT {MAX_ROWS}"
    )


def test_limit_above_the_cap_is_capped_by_wrapping():
    assert accepted("SELECT widget_name FROM marts.widget_sales LIMIT 100000") == (
        f"SELECT * FROM (\nSELECT widget_name FROM marts.widget_sales LIMIT 100000\n) LIMIT {MAX_ROWS}"
    )


def test_union_and_limit_by_are_capped_by_wrapping():
    union = "SELECT sale_ref FROM marts.widget_sales UNION ALL SELECT sale_ref FROM marts.widget_refunds"
    limit_by = "SELECT widget_name, sold_on FROM marts.widget_sales ORDER BY sold_on LIMIT 1 BY widget_name"

    assert accepted(union).startswith("SELECT * FROM (\n") and accepted(union).endswith(f") LIMIT {MAX_ROWS}")
    assert accepted(limit_by).endswith(f") LIMIT {MAX_ROWS}")


def test_aliases_in_the_select_list_and_clauses_are_accepted():
    accepted(
        "SELECT sum(sale_amount) AS total, total * 2 AS doubled FROM marts.widget_sales "
        "GROUP BY widget_name HAVING doubled > 0 ORDER BY total DESC LIMIT 5"
    )


def test_fully_qualified_columns_are_accepted():
    accepted("SELECT marts.widget_sales.widget_name AS widget_name FROM marts.widget_sales LIMIT 5")


@pytest.mark.parametrize("limit", ["1.5", "1e3"])
def test_non_integer_limit_is_wrapped_instead_of_raising(limit):
    assert accepted(f"SELECT widget_name FROM marts.widget_sales LIMIT {limit}").endswith(f") LIMIT {MAX_ROWS}")


def test_count_star_is_accepted():
    accepted("SELECT count(*) AS sales FROM marts.widget_sales")


def test_unterminated_string_is_an_sql_error_to_retry():
    error = rejected("SELECT 'abc FROM marts.widget_sales")

    assert error.category == "sql"
    assert error.message.startswith("SQL does not parse")


def test_unparsable_sql_is_an_sql_error_to_retry():
    error = rejected("SELECT widget_name FROM marts.widget_sales WHERE")

    assert error.category == "sql"
    assert error.message.startswith("SQL does not parse")


@pytest.mark.parametrize(("sql", "message"), [
    ("SELECT 1 FROM marts.widget_sales; SELECT 2 FROM marts.widget_sales", "exactly one statement"),
    ("DROP TABLE marts.widget_sales", "only SELECT"),
    ("INSERT INTO marts.widget_sales SELECT * FROM marts.widget_sales", "only SELECT"),
    ("ALTER TABLE marts.widget_sales DELETE WHERE 1", "only SELECT"),
    ("SELECT secret FROM marts.widget_sales", "column secret is not an approved column"),
    ("SELECT secret AS secret FROM marts.widget_sales", "column secret is not an approved column"),
    ("SELECT secret AS a, a AS secret FROM marts.widget_sales", "column secret is not an approved column"),
    ("SELECT secret FROM marts.widget_sales WHERE 1 IN (SELECT 1 AS secret)", "column secret is not an approved column"),
    ("SELECT w.refund_total FROM marts.widget_sales AS w", "column refund_total is not an approved column of w"),
    ("SELECT q.secret FROM (SELECT widget_name FROM marts.widget_sales) AS q", "column secret is not an approved column of q"),
    ("SELECT COLUMNS('.*') FROM marts.widget_sales", "function columns()"),
    ("SELECT tuple(*) AS t FROM marts.widget_sales", "* is allowed only in count(*) or a select list"),
    ("SELECT toString(w.*) AS t FROM marts.widget_sales AS w", "* is allowed only in count(*) or a select list"),
    ("SELECT widget_name FROM marts.customers", "is not an approved dataset"),
    ("SELECT widget_name FROM raw.widget_sales", "is not an approved dataset"),
    ("SELECT name FROM system.tables", "system table system.tables"),
    ("SELECT * FROM file('/etc/passwd')", "table function file()"),
    ("SELECT * FROM remote('host', marts.widget_sales)", "table function remote()"),
    ("SELECT number FROM numbers(10)", "table function numbers()"),
    ("SELECT url('http://example.com') AS u, widget_name FROM marts.widget_sales", "function url()"),
    ("SELECT widget_name FROM marts.widget_sales WHERE sleep(3) = 0", "function sleep()"),
    ("SELECT dictGet('d', 'a', sale_ref) AS v FROM marts.widget_sales", "function dictget()"),
    ("SELECT widget_name FROM marts.widget_sales SETTINGS max_execution_time = 9999", "SETTINGS"),
    ("SELECT widget_name FROM marts.widget_sales FORMAT JSON", "FORMAT"),
    ("SELECT * FROM marts.widget_sales", "SELECT * is not allowed"),
    ("SELECT x.widget_name FROM marts.widget_sales", "refers to an unknown table"),
    ("SELECT 1 AS one", "reads no approved dataset"),
])
def test_rejections_are_policy_errors(sql, message):
    error = rejected(sql)

    assert error.category == "policy"
    assert error.node == "guard"
    assert message in error.message


@pytest.mark.parametrize("sql", [
    # an unapproved table read beside an approved one
    "SELECT w.widget_name FROM secrets AS s JOIN marts.widget_sales AS w ON s.sale_ref = w.sale_ref "
    "WHERE 1 IN (WITH secrets AS (SELECT 1 AS x) SELECT x FROM secrets)",
    # SELECT * over an approved table that a nested CTE name would otherwise excuse
    "SELECT * FROM widget_sales WHERE sale_ref IN "
    "(WITH widget_sales AS (SELECT sale_ref FROM marts.widget_refunds) SELECT sale_ref FROM widget_sales)",
])
def test_a_nested_cte_cannot_hide_an_outer_table(sql):
    assert rejected(sql).category == "policy"


def test_star_over_a_cte_is_accepted():
    accepted("WITH w AS (SELECT widget_name FROM marts.widget_sales) SELECT * FROM w LIMIT 3")


def test_subquery_reading_a_forbidden_table_is_rejected():
    error = rejected("SELECT widget_name FROM marts.widget_sales WHERE sale_ref IN (SELECT sale_ref FROM raw.secrets)")

    assert "raw.secrets" in error.message


def test_unqualified_allowlisted_table_is_accepted():
    accepted("SELECT widget_name FROM widget_sales LIMIT 1")
