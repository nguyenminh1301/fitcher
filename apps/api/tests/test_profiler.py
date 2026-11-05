from datetime import UTC, date, datetime
import re

import pytest

from app.onboarding.profiler import base_type, profile_marts
from app.packs.compiler import CompileError

CLOCK = lambda: datetime(2026, 11, 5, 8, 0, tzinfo=UTC)  # noqa: E731


class ScriptedWarehouse:
    """Answers each query from the first pattern that matches it; records every query and its settings."""

    def __init__(self, columns, answers):
        self.columns = columns
        self.answers = answers
        self.queries = []

    def query(self, sql, settings=None):
        self.queries.append((sql, settings))
        if "system.columns" in sql:
            return self.columns
        for pattern, rows in self.answers:
            if re.search(pattern, sql):
                return rows
        raise AssertionError(f"unexpected query {sql}")


COLUMNS = [
    ("orders", "order_id", "String"),
    ("orders", "placed_on", "Date"),
    ("orders", "channel", "LowCardinality(String)"),
    ("orders", "amount", "Nullable(Float64)"),
    ("lines", "order_id", "String"),
    ("lines", "note", "String"),
]


def standard_answers(order_rows=3):
    return [
        (r"SELECT count\(\) FROM `marts`\.`orders`", [(order_rows,)]),
        (r"SELECT count\(\) FROM `marts`\.`lines`", [(5,)]),
        (r"uniqExact\(`order_id`\) FROM `marts`\.`orders`", [(3,)]),
        (r"uniqExact\(`placed_on`\)", [(2,)]),
        (r"uniqExact\(`channel`\)", [(2,)]),
        (r"uniqExact\(`amount`\)", [(3,)]),
        (r"uniqExact\(`order_id`\) FROM `marts`\.`lines`", [(3,)]),
        (r"uniqExact\(`note`\)", [(400,)]),
        (r"min\(`placed_on`\), max\(`placed_on`\)", [(date(2024, 1, 1), date(2024, 3, 31))]),
        (r"toString\(`channel`\)", [("web", 2), ("store", 1)]),
        (r"toString\(`order_id`\) AS value.*`orders`", [("o1", 1), ("o2", 1), ("o3", 1)]),
        (r"toString\(`order_id`\) AS value.*`lines`", [("o1", 2), ("o2", 2), ("o3", 1)]),
        (r"uniqExactIf\(`order_id`, `order_id` IN \(SELECT `order_id` FROM `marts`\.`lines`\)\)", [(1.0,)]),
        (r"uniqExactIf\(`order_id`, `order_id` IN \(SELECT `order_id` FROM `marts`\.`orders`\)\)", [(1.0,)]),
        (r"SELECT \* FROM `marts`\.`orders` LIMIT 3", [("o1", date(2024, 1, 1), "web", 10.5)]),
        (r"SELECT \* FROM `marts`\.`lines` LIMIT 3", [("o1", "gift")]),
    ]


def test_profile_reads_rows_dates_distincts_top_values_samples_and_join_candidates():
    warehouse = ScriptedWarehouse(COLUMNS, standard_answers())

    profile = profile_marts(warehouse, ["orders", "lines"], top_k=5, low_cardinality=50, sample_rows=3, clock=CLOCK)

    assert profile["profiled_at"] == "2026-11-05T08:00:00+00:00"
    orders = profile["tables"]["orders"]
    assert orders["rows"] == 3
    assert orders["columns"]["placed_on"] == {"type": "date", "distinct": 2, "min": "2024-01-01", "max": "2024-03-31"}
    assert orders["columns"]["channel"] == {"type": "string", "distinct": 2, "top_values": [["web", 2], ["store", 1]]}
    assert orders["columns"]["amount"] == {"type": "number", "distinct": 3}
    assert orders["sample_rows"] == [["o1", "2024-01-01", "web", 10.5]]
    # A string column above the low-cardinality limit gets no top values.
    assert "top_values" not in profile["tables"]["lines"]["columns"]["note"]
    assert profile["join_candidates"] == [{"left": "lines.order_id", "right": "orders.order_id", "overlap": 1.0}]


def test_every_profile_query_carries_the_scan_limits():
    warehouse = ScriptedWarehouse(COLUMNS, standard_answers())
    profile_marts(warehouse, ["orders", "lines"], clock=CLOCK)
    assert all(settings and settings["readonly"] == 2 and settings["max_execution_time"] for _, settings in warehouse.queries)


def test_an_empty_table_has_no_dates_values_or_samples():
    answers = [(r"SELECT count\(\) FROM `marts`\.`orders`", [(0,)])]
    warehouse = ScriptedWarehouse([c for c in COLUMNS if c[0] == "orders"], answers)

    profile = profile_marts(warehouse, ["orders"], clock=CLOCK)

    assert profile["tables"]["orders"] == {
        "rows": 0,
        "columns": {
            "order_id": {"type": "string", "distinct": 0},
            "placed_on": {"type": "date", "distinct": 0},
            "channel": {"type": "string", "distinct": 0},
            "amount": {"type": "number", "distinct": 0},
        },
        "sample_rows": [],
    }
    assert profile["join_candidates"] == []


def test_a_table_missing_from_marts_is_reported():
    warehouse = ScriptedWarehouse(COLUMNS, standard_answers())
    with pytest.raises(CompileError, match="marts has no table 'missing'"):
        profile_marts(warehouse, ["orders", "missing"], clock=CLOCK)


def test_an_unsafe_table_name_is_refused_before_any_query():
    warehouse = ScriptedWarehouse(COLUMNS, standard_answers())
    with pytest.raises(CompileError, match="unsafe identifier"):
        profile_marts(warehouse, ["orders; DROP TABLE x"], clock=CLOCK)
    assert warehouse.queries == []


@pytest.mark.parametrize(("clickhouse", "expected"), [
    ("LowCardinality(Nullable(String))", "string"),
    ("DateTime64(3, 'UTC')", "datetime"),
    ("Date32", "date"),
    ("Decimal(18, 2)", "number"),
    ("UInt8", "number"),
    ("Bool", "boolean"),
    ("Array(String)", "other"),
])
def test_base_type_maps_clickhouse_types_to_pack_types(clickhouse, expected):
    assert base_type(clickhouse) == expected
