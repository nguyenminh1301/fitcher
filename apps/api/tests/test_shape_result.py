"""Shaping query output into a Result: columns grouped to a time grain."""


def test_a_date_column_grouped_to_a_grain_is_marked_and_headed_in_the_question_language():
    from app.agent.nodes.shape_result import with_grain
    from app.contracts.result import ColumnInfo, Result

    result = Result(columns=[ColumnInfo(name="sold_on_period", type="date", role="time"),
                             ColumnInfo(name="total", type="number", role="measure", label="Total")],
                    rows=[["2026-01-01", 1.0]], row_count=1)

    columns = with_grain(result, "month", "vi").columns

    assert (columns[0].grain, columns[0].label) == ("month", "Tháng")
    assert (columns[1].grain, columns[1].label) == (None, "Total")
    assert with_grain(result, None, "en") is result
