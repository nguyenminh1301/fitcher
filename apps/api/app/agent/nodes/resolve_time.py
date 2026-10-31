"""Turn extracted period descriptors into labelled half-open date ranges.

``extract`` never emits dates for relative phrases; it emits descriptors, and
this module is the only place that computes dates, so time logic stays
deterministic and testable. Quarters and years follow the pack's fiscal
calendar unless the descriptor asks for the calendar one. A fiscal year is
named after the calendar year in which it ends: with an April start, FY2025
runs from 2024-04-01 to 2025-04-01. With a January start both calendars are
the same and labels use the plain calendar form.

The reference date is "today" in the user's time zone; clients without one
pass UTC (DECISIONS §6).
"""

from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta
from typing import Literal, Self
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.contracts.query_spec import Period

Unit = Literal["day", "week", "month", "quarter", "year"]


class TimeResolutionError(ValueError):
    """The descriptors cannot be turned into valid periods."""


class PeriodDescriptor(BaseModel):
    """One period as extracted from the question, without computed dates.

    - ``year``: ``year``; ``quarter``: ``year`` + ``quarter``; ``month``: ``year`` + ``month``.
    - ``range``: explicit ``start`` and ``end`` dates, ``end`` inclusive as people say it.
    - ``relative``: the ``unit`` that is ``offset`` units from the current one
      (0 = this, -1 = last), e.g. "last quarter" is quarter/-1.
    - ``to_date``: the current ``unit`` (week, month, quarter or year) up to and
      including the reference date, e.g. "this year to date".
    - ``last_n``: the ``count`` most recent ``unit``s ending on the reference date.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["year", "quarter", "month", "range", "relative", "to_date", "last_n"]
    calendar: Literal["fiscal", "calendar"] = "fiscal"
    year: int | None = Field(default=None, ge=1900, le=2200)
    quarter: int | None = Field(default=None, ge=1, le=4)
    month: int | None = Field(default=None, ge=1, le=12)
    start: date | None = None
    end: date | None = None
    unit: Unit | None = None
    offset: int | None = Field(default=None, ge=-1000, le=1000)
    count: int | None = Field(default=None, ge=1, le=1000)

    @model_validator(mode="after")
    def _fields_for_kind(self) -> Self:
        required = {
            "year": ("year",),
            "quarter": ("year", "quarter"),
            "month": ("year", "month"),
            "range": ("start", "end"),
            "relative": ("unit", "offset"),
            "to_date": ("unit",),
            "last_n": ("unit", "count"),
        }[self.kind]
        missing = [name for name in required if getattr(self, name) is None]
        if missing:
            raise ValueError(f"a {self.kind} period needs {', '.join(missing)}")
        if self.kind == "range" and self.end < self.start:
            raise ValueError(f"range end {self.end} is before its start {self.start}")
        if self.kind == "to_date" and self.unit == "day":
            raise ValueError("a to_date period needs a unit longer than a day")
        return self


def reference_date(timezone: str | None, now: datetime | None = None) -> date:
    """Today's date in ``timezone`` (an IANA name), or in UTC when none is given."""
    try:
        zone = ZoneInfo(timezone) if timezone else UTC
    except (ZoneInfoNotFoundError, ValueError):
        raise TimeResolutionError(f"unknown time zone {timezone!r}") from None
    return (now or datetime.now(UTC)).astimezone(zone).date()


def _add_months(day: date, months: int) -> date:
    """Shift by whole months, keeping the day and clamping it to the target month's length."""
    index = day.year * 12 + day.month - 1 + months
    year, month = index // 12, index % 12 + 1
    following = date(year + month // 12, month % 12 + 1, 1)
    return date(year, month, min(day.day, (following - timedelta(days=1)).day))


class _Calendar:
    def __init__(self, fiscal_start_month: int, calendar: str):
        self.start_month = fiscal_start_month if calendar == "fiscal" else 1
        self.fiscal = self.start_month != 1

    def year_start(self, year: int) -> date:
        """First day of (fiscal) year ``year``."""
        return date(year - 1 if self.fiscal else year, self.start_month, 1)

    def year_of(self, day: date) -> int:
        """The (fiscal) year containing ``day``."""
        return day.year + 1 if self.fiscal and day.month >= self.start_month else day.year

    def quarter_start(self, year: int, quarter: int) -> date:
        return _add_months(self.year_start(year), 3 * (quarter - 1))

    def quarter_of(self, day: date) -> tuple[int, int]:
        year = self.year_of(day)
        months = (day.year * 12 + day.month) - (self.year_start(year).year * 12 + self.year_start(year).month)
        return year, months // 3 + 1

    def year_label(self, year: int) -> str:
        return f"FY{year}" if self.fiscal else str(year)

    def quarter_label(self, year: int, quarter: int) -> str:
        return f"FY{year} Q{quarter}" if self.fiscal else f"Q{quarter} {year}"


def _unit_start(unit: Unit, day: date, cal: _Calendar) -> date:
    if unit == "day":
        return day
    if unit == "week":
        return day - timedelta(days=day.weekday())
    if unit == "month":
        return day.replace(day=1)
    if unit == "quarter":
        return cal.quarter_start(*cal.quarter_of(day))
    return cal.year_start(cal.year_of(day))


def _shift(unit: Unit, start: date, units: int) -> date:
    if unit == "day":
        return start + timedelta(days=units)
    if unit == "week":
        return start + timedelta(weeks=units)
    return _add_months(start, units * {"month": 1, "quarter": 3, "year": 12}[unit])


def _unit_label(unit: Unit, start: date, cal: _Calendar) -> str:
    if unit == "day":
        return start.isoformat()
    if unit == "week":
        iso = start.isocalendar()
        return f"{iso.year}-W{iso.week:02d}"
    if unit == "month":
        return start.strftime("%Y-%m")
    if unit == "quarter":
        return cal.quarter_label(*cal.quarter_of(start))
    return cal.year_label(cal.year_of(start))


def resolve_period(descriptor: PeriodDescriptor, today: date, fiscal_start_month: int) -> Period:
    cal = _Calendar(fiscal_start_month, descriptor.calendar)
    d = descriptor
    if d.kind == "year":
        start = cal.year_start(d.year)
        return Period(label=cal.year_label(d.year), start=start, end=_add_months(start, 12))
    if d.kind == "quarter":
        start = cal.quarter_start(d.year, d.quarter)
        return Period(label=cal.quarter_label(d.year, d.quarter), start=start, end=_add_months(start, 3))
    if d.kind == "month":
        start = date(d.year, d.month, 1)
        return Period(label=start.strftime("%Y-%m"), start=start, end=_add_months(start, 1))
    if d.kind == "range":
        return Period(label=f"{d.start.isoformat()} to {d.end.isoformat()}", start=d.start, end=d.end + timedelta(days=1))
    if d.kind == "relative":
        start = _shift(d.unit, _unit_start(d.unit, today, cal), d.offset)
        return Period(label=_unit_label(d.unit, start, cal), start=start, end=_shift(d.unit, start, 1))
    end = today + timedelta(days=1)
    if d.kind == "to_date":
        start = _unit_start(d.unit, today, cal)
        return Period(label=f"{_unit_label(d.unit, start, cal)} to {today.isoformat()}", start=start, end=end)
    start = _shift(d.unit, end, -d.count)
    return Period(label=f"last {d.count} {d.unit}s to {today.isoformat()}", start=start, end=end)


def resolve_periods(
    descriptors: Sequence[PeriodDescriptor], today: date, fiscal_start_month: int
) -> list[Period]:
    """Resolve every descriptor; labels must come out distinct."""
    if not 1 <= fiscal_start_month <= 12:
        raise TimeResolutionError(f"fiscal start month must be 1-12, got {fiscal_start_month}")
    if not descriptors:
        raise TimeResolutionError("no period to resolve")
    periods = [resolve_period(descriptor, today, fiscal_start_month) for descriptor in descriptors]
    labels = [period.label for period in periods]
    if len(set(labels)) != len(labels):
        raise TimeResolutionError(f"the question names the same period twice: {labels}")
    return periods
