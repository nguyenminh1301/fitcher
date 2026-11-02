"""Comparing an answer's result set with the reference result by column values."""

from decimal import Decimal

from app.contracts.result import ColumnInfo, Result
from app.eval.compare import Tolerance, compare_results, values_match


def table(columns: list[tuple[str, str]], rows: list[list]) -> Result:
    infos = [
        ColumnInfo(name=name, type="number" if role == "measure" else "string", role=role) for name, role in columns
    ]
    return Result(columns=infos, rows=rows, row_count=len(rows))


EXPECTED = table(
    [("product", "dimension"), ("revenue_2025", "measure"), ("revenue_2024", "measure")],
    [["A", 300.0, 100.0], ["B", 200.0, 250.0], ["C", 50.0, 0.0]],
)


def test_identical_results_match():
    assert compare_results(EXPECTED, EXPECTED, ordered=True).match is True


def test_reordered_and_renamed_columns_match():
    actual = table(
        [("revenue_2024_x", "measure"), ("item", "dimension"), ("revenue_2025_x", "measure")],
        [[100.0, "A", 300.0], [250.0, "B", 200.0], [0.0, "C", 50.0]],
    )

    assert compare_results(EXPECTED, actual, ordered=True).match is True


def _scalar(value) -> Result:
    return table([("total", "measure")], [[value]])


def test_float_noise_within_relative_tolerance():
    assert compare_results(_scalar(1000.0), _scalar(1000.0000001), ordered=False).match is True
    outcome = compare_results(_scalar(1000.0), _scalar(1000.01), ordered=False)
    assert outcome.match is False
    assert outcome.reason == "no column matches measure total"


def test_zero_valued_measures_compare_safely():
    assert compare_results(_scalar(0.0), _scalar(1e-12), ordered=False).match is True
    assert compare_results(_scalar(0.0), _scalar(1e-6), ordered=False).match is False


def test_int_decimal_and_float_compare_equal():
    assert compare_results(_scalar(10), _scalar(Decimal("10.00")), ordered=False).match is True
    assert compare_results(_scalar(10), _scalar(10.0), ordered=False).match is True


def test_null_measures_match_only_null():
    assert values_match(None, None, Tolerance()) is True
    assert compare_results(_scalar(None), _scalar(None), ordered=False).match is True
    assert compare_results(_scalar(None), _scalar(0), ordered=False).match is False


def test_missing_row():
    actual = table(EXPECTED_COLUMNS, EXPECTED.rows[:2])

    assert compare_results(EXPECTED, actual, ordered=False).reason == "expected 3 rows, got 2"


def test_extra_row():
    expected = table(EXPECTED_COLUMNS, EXPECTED.rows[:2])

    assert compare_results(expected, EXPECTED, ordered=False).reason == "expected 2 rows, got 3"


EXPECTED_COLUMNS = [("product", "dimension"), ("revenue_2025", "measure"), ("revenue_2024", "measure")]


def test_rank_order_difference_fails_only_when_ordered():
    swapped = table(EXPECTED_COLUMNS, [EXPECTED.rows[1], EXPECTED.rows[0], EXPECTED.rows[2]])

    assert compare_results(EXPECTED, swapped, ordered=False).match is True
    assert compare_results(EXPECTED, swapped, ordered=True).reason == "row order differs at row 0"


def test_extra_actual_columns_are_allowed():
    actual = table(
        [*EXPECTED_COLUMNS, ("brand", "dimension"), ("revenue_pct", "measure")],
        [[*row, "Acme", 1.5] for row in EXPECTED.rows],
    )

    assert compare_results(EXPECTED, actual, ordered=True).match is True


def test_missing_measure_column_fails():
    actual = table(EXPECTED_COLUMNS[:2], [row[:2] for row in EXPECTED.rows])

    assert compare_results(EXPECTED, actual, ordered=True).reason == "no column matches measure revenue_2024"


def test_different_key_values_fail():
    actual = table(EXPECTED_COLUMNS, [["A", 300.0, 100.0], ["B", 200.0, 250.0], ["D", 50.0, 0.0]])

    assert compare_results(EXPECTED, actual, ordered=False).reason == "no column matches key column product"


def test_duplicate_keys_align_by_sorted_rows():
    columns = [("product", "dimension"), ("revenue", "measure")]
    expected = table(columns, [["A", 1.0], ["A", 2.0], ["B", 3.0]])
    actual = table(columns, [["B", 3.0], ["A", 2.0], ["A", 1.0]])

    assert compare_results(expected, actual, ordered=False).match is True


def test_null_and_mixed_type_keys_sort_without_error():
    columns = [("label", "dimension"), ("revenue", "measure")]
    expected = table(columns, [[None, 1.0], ["2025-01-01", 2.0], [7, 3.0]])
    actual = table(columns, [[7, 3.0], [None, 1.0], ["2025-01-01", 2.0]])

    assert compare_results(expected, actual, ordered=False).match is True


def test_scalar_result_without_keys():
    assert compare_results(_scalar(42.5), _scalar(42.5), ordered=False).match is True


DUPLICATE_KEYS = table(
    [("product", "dimension"), ("units", "measure"), ("revenue", "measure")],
    [["A", 1.0, 100.0], ["A", 2.0, 50.0]],
)


def test_duplicate_key_rows_match_with_reordered_measure_columns():
    actual = table(
        [("revenue_x", "measure"), ("item", "dimension"), ("units_x", "measure")],
        [[100.0, "A", 1.0], [50.0, "A", 2.0]],
    )

    assert compare_results(DUPLICATE_KEYS, actual, ordered=False).match is True


def test_duplicate_key_rows_with_recombined_measures_do_not_match():
    actual = table(
        [("product", "dimension"), ("units", "measure"), ("revenue", "measure")],
        [["A", 1.0, 50.0], ["A", 2.0, 100.0]],
    )

    assert compare_results(DUPLICATE_KEYS, actual, ordered=False).match is False


def test_a_missing_key_combination_names_the_reference_row_not_its_values():
    columns = [("product", "dimension"), ("region", "dimension"), ("revenue", "measure")]
    expected = table(columns, [["Alice Nguyen", "West", 1.0], ["Bob Tran", "East", 2.0]])
    actual = table(columns, [["Alice Nguyen", "East", 1.0], ["Bob Tran", "West", 2.0]])

    reason = compare_results(expected, actual, ordered=False).reason

    assert reason == "no answer row matches the key of reference row 0"


def test_unpaired_measures_name_the_reference_row_not_its_values():
    columns = [("product", "dimension"), ("units", "measure"), ("revenue", "measure")]
    expected = table(columns, [["Alice Nguyen", 1.0, 10.0], ["Alice Nguyen", 2.0, 20.0]])
    actual = table(columns, [["Alice Nguyen", 1.0, 20.0], ["Alice Nguyen", 2.0, 10.0]])

    reason = compare_results(expected, actual, ordered=False).reason

    assert reason == "no answer row matches the measures of reference row 0"
