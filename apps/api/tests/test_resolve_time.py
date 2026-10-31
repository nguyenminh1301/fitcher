"""Deterministic period resolution: descriptors in, labelled [start, end) dates out."""

from datetime import UTC, date, datetime

import pytest

from app.agent.nodes.resolve_time import (
    PeriodDescriptor,
    TimeResolutionError,
    reference_date,
    resolve_period,
    resolve_periods,
)

TODAY = date(2026, 1, 15)


def resolve(fiscal_start_month: int = 1, today: date = TODAY, **descriptor):
    period = resolve_period(PeriodDescriptor(**descriptor), today, fiscal_start_month)
    return period.label, period.start.isoformat(), period.end.isoformat()


def test_calendar_first_quarter():
    assert resolve(kind="quarter", year=2024, quarter=1) == ("Q1 2024", "2024-01-01", "2024-04-01")


def test_fiscal_year_starting_in_april_is_named_by_its_end_year():
    assert resolve(4, kind="year", year=2025) == ("FY2025", "2024-04-01", "2025-04-01")
    assert resolve(4, kind="quarter", year=2025, quarter=1) == ("FY2025 Q1", "2024-04-01", "2024-07-01")
    assert resolve(4, kind="quarter", year=2025, quarter=4) == ("FY2025 Q4", "2025-01-01", "2025-04-01")


def test_calendar_quarter_ignores_the_fiscal_start_when_asked():
    assert resolve(4, kind="quarter", year=2025, quarter=1, calendar="calendar") == ("Q1 2025", "2025-01-01", "2025-04-01")


def test_last_quarter_crosses_the_year_boundary():
    assert resolve(kind="relative", unit="quarter", offset=-1) == ("Q4 2025", "2025-10-01", "2026-01-01")


def test_last_fiscal_quarter_with_an_april_start():
    # 2026-01-15 is in FY2026 Q4 (Jan-Mar 2026); the previous quarter is Oct-Dec 2025.
    assert resolve(4, kind="relative", unit="quarter", offset=-1) == ("FY2026 Q3", "2025-10-01", "2026-01-01")


def test_this_and_last_year_and_month():
    assert resolve(kind="relative", unit="year", offset=0) == ("2026", "2026-01-01", "2027-01-01")
    assert resolve(kind="relative", unit="month", offset=-1) == ("2025-12", "2025-12-01", "2026-01-01")


def test_last_week_is_the_previous_iso_week():
    # 2026-01-15 is a Thursday; ISO week 3 starts Monday 2026-01-12.
    assert resolve(kind="relative", unit="week", offset=-1) == ("2026-W02", "2026-01-05", "2026-01-12")


def test_two_periods_for_comparison():
    periods = resolve_periods(
        [PeriodDescriptor(kind="quarter", year=2024, quarter=1), PeriodDescriptor(kind="quarter", year=2025, quarter=1)],
        TODAY,
        1,
    )

    assert [(p.label, p.start.isoformat(), p.end.isoformat()) for p in periods] == [
        ("Q1 2024", "2024-01-01", "2024-04-01"),
        ("Q1 2025", "2025-01-01", "2025-04-01"),
    ]


def test_month_and_year():
    assert resolve(kind="month", year=2024, month=2) == ("2024-02", "2024-02-01", "2024-03-01")
    assert resolve(kind="month", year=2024, month=12) == ("2024-12", "2024-12-01", "2025-01-01")
    assert resolve(kind="year", year=2024) == ("2024", "2024-01-01", "2025-01-01")


def test_explicit_range_end_is_inclusive_in_the_question():
    assert resolve(kind="range", start=date(2024, 3, 5), end=date(2024, 3, 31)) == (
        "2024-03-05 to 2024-03-31", "2024-03-05", "2024-04-01",
    )


def test_year_to_date_includes_the_reference_day():
    assert resolve(kind="to_date", unit="year") == ("2026 to 2026-01-15", "2026-01-01", "2026-01-16")
    assert resolve(4, kind="to_date", unit="year") == ("FY2026 to 2026-01-15", "2025-04-01", "2026-01-16")


def test_last_n_units_end_on_the_reference_day():
    assert resolve(kind="last_n", unit="day", count=7) == ("last 7 days to 2026-01-15", "2026-01-09", "2026-01-16")
    assert resolve(kind="last_n", unit="month", count=3, today=date(2026, 5, 30)) == (
        "last 3 months to 2026-05-30", "2026-02-28", "2026-05-31",
    )


@pytest.mark.parametrize("descriptor", [
    {"kind": "quarter", "year": 2024},
    {"kind": "quarter", "year": 2024, "quarter": 5},
    {"kind": "month", "year": 2024, "month": 13},
    {"kind": "relative", "unit": "quarter"},
    {"kind": "range", "start": "2024-03-31", "end": "2024-03-01"},
    {"kind": "to_date", "unit": "day"},
    {"kind": "last_n", "unit": "day", "count": 0},
    {"kind": "decade", "year": 2020},
    {"kind": "year", "year": 2024, "label": "extra field"},
])
def test_invalid_descriptors_are_rejected(descriptor):
    with pytest.raises(ValueError):
        PeriodDescriptor(**descriptor)


def test_the_same_period_twice_is_rejected():
    twice = [PeriodDescriptor(kind="year", year=2024), PeriodDescriptor(kind="relative", unit="year", offset=-2)]

    with pytest.raises(TimeResolutionError, match="same period twice"):
        resolve_periods(twice, TODAY, 1)


def test_no_period_and_bad_fiscal_month_are_rejected():
    with pytest.raises(TimeResolutionError, match="no period"):
        resolve_periods([], TODAY, 1)
    with pytest.raises(TimeResolutionError, match="fiscal start month"):
        resolve_periods([PeriodDescriptor(kind="year", year=2024)], TODAY, 0)


def test_reference_date_uses_the_users_time_zone():
    now = datetime(2025, 12, 31, 20, 0, tzinfo=UTC)

    assert reference_date("Asia/Ho_Chi_Minh", now) == date(2026, 1, 1)
    assert reference_date("America/Los_Angeles", now) == date(2025, 12, 31)
    assert reference_date(None, now) == date(2025, 12, 31)


def test_unknown_time_zone_is_rejected():
    with pytest.raises(TimeResolutionError, match="unknown time zone"):
        reference_date("Mars/Olympus", datetime(2025, 1, 1, tzinfo=UTC))
