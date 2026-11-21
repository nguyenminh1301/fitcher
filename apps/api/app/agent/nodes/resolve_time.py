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
import re
from typing import TYPE_CHECKING, Literal, Self
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.agent.nodes.clarify import chosen
from app.contracts.query_spec import Period

if TYPE_CHECKING:
    from app.agent.state import AgentDeps, AgentState

Unit = Literal["day", "week", "month", "quarter", "year"]


# The first and last days a period may span, the years the extraction accepts.
EARLIEST = date(1900, 1, 1)
LATEST = date(2200, 12, 31)


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
        # "All time" can come back as a range to 9999-12-31; the range is held to the dates a period may span.
        start, last = max(d.start, EARLIEST), min(d.end, LATEST)
        if last < start:
            raise TimeResolutionError(f"the range {d.start} to {d.end} is outside the dates a period may span")
        return Period(label=f"{start.isoformat()} to {last.isoformat()}", start=start, end=last + timedelta(days=1))
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


_YEAR = r"((?:19|20|21)\d{2})"
_MONTH_NAMES = ("january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
                "november", "december")
# Spelled-out periods in English and Vietnamese, most specific first: a quarter or month claims its year.
_EXPLICIT = (
    ("quarter", re.compile(rf"\b(?:q|quý|quy)\s*([1-4])\s*(?:/|-|,|năm|nam|of)?\s*{_YEAR}\b", re.IGNORECASE)),
    ("month", re.compile(rf"\b(?:tháng|thang)\s*(1[0-2]|0?[1-9])\s*(?:/|-|,|năm|nam)?\s*{_YEAR}\b", re.IGNORECASE)),
    ("month_name", re.compile(rf"\b({'|'.join(_MONTH_NAMES)})\s*,?\s*{_YEAR}\b", re.IGNORECASE)),
    ("year", re.compile(rf"\b(?:năm|nam|year|fy|in)\s*{_YEAR}\b", re.IGNORECASE)),
)


def explicit_periods(question: str) -> list[PeriodDescriptor]:
    """Years, quarters and months the question names outright ("năm 2026", "Q1 2025", "March 2024"), in order.

    Only used when the extraction returned no period: relative phrases stay with the model, and a year that is
    part of a quarter or month is not counted again. Duplicates are dropped.
    """
    found: list[tuple[int, PeriodDescriptor]] = []
    claimed: list[range] = []
    for kind, pattern in _EXPLICIT:
        for match in pattern.finditer(question or ""):
            if any(match.start() in span for span in claimed):
                continue
            claimed.append(range(match.start(), match.end()))
            if kind == "quarter":
                descriptor = PeriodDescriptor(kind="quarter", quarter=int(match[1]), year=int(match[2]))
            elif kind == "month":
                descriptor = PeriodDescriptor(kind="month", month=int(match[1]), year=int(match[2]))
            elif kind == "month_name":
                descriptor = PeriodDescriptor(kind="month", month=_MONTH_NAMES.index(match[1].lower()) + 1, year=int(match[2]))
            else:
                descriptor = PeriodDescriptor(kind="year", year=int(match[1]))
            found.append((match.start(), descriptor))
    unique: list[PeriodDescriptor] = []
    for _, descriptor in sorted(found, key=lambda item: item[0]):
        if descriptor not in unique:
            unique.append(descriptor)
    return unique


_GRAIN_WORDS = {
    "day": ("ngày", "ngay", "day", "daily"), "week": ("tuần", "tuan", "week", "weekly"),
    "month": ("tháng", "thang", "month", "monthly"), "quarter": ("quý", "quy", "quarter", "quarterly"),
    "year": ("năm", "nam", "year", "yearly", "annually"),
}
_GRAIN = re.compile(
    r"\b(?:(?:theo|từng|tung|mỗi|moi|hàng|hang|by|per|each)\s+(\w+)|(daily|weekly|monthly|quarterly|yearly|annually))\b",
    re.IGNORECASE,
)


def explicit_time_grain(question: str) -> Unit | None:
    """The time grain a question asks for outright ("theo tháng", "by quarter", "monthly"), or None.

    Used only when the extraction returned no grain. A word right after "theo"/"by" that is not a time unit
    ("theo khu vực", "by region") is ignored.
    """
    for match in _GRAIN.finditer(question or ""):
        word = (match[1] or match[2]).lower()
        for grain, words in _GRAIN_WORDS.items():
            if word in words:
                return grain  # type: ignore[return-value]
    return None


# The period options of a clarifying question (``clarify.PERIODS``) as descriptors; "all" is handled apart.
CHOSEN_PERIODS: dict[str, PeriodDescriptor] = {
    "this_month": PeriodDescriptor(kind="relative", unit="month", offset=0),
    "last_month": PeriodDescriptor(kind="relative", unit="month", offset=-1),
    "this_quarter": PeriodDescriptor(kind="relative", unit="quarter", offset=0),
    "last_quarter": PeriodDescriptor(kind="relative", unit="quarter", offset=-1),
    "this_year": PeriodDescriptor(kind="relative", unit="year", offset=0),
    "last_year": PeriodDescriptor(kind="relative", unit="year", offset=-1),
}

# Words that say a question covers all of the data, in English and Vietnamese.
_ALL_TIME = re.compile(
    r"\b(?:all[- ]time|of all time|overall|ever|in total|so far|to date)\b"
    r"|toàn bộ|tất cả thời gian|từ trước (?:đến|tới) nay|từ trước giờ|tổng cộng|tính đến nay",
    re.IGNORECASE,
)


def says_all_time(question: str) -> bool:
    """The question asks about all of the data ("in total", "overall", "tổng cộng"), so it needs no period."""
    return bool(_ALL_TIME.search(question or ""))


class PeriodShift(BaseModel):
    """A follow-up's periods as the previous query's periods moved by ``offset`` ``unit``s (0 keeps them)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    unit: Unit
    offset: int = Field(ge=-1000, le=1000)


def _period_label(start: date, end: date, cal: _Calendar) -> str:
    """The usual label of a whole year, quarter or month, otherwise the dates it covers."""
    for unit in ("year", "quarter", "month"):
        if start == _unit_start(unit, start, cal) and end == _shift(unit, start, 1):
            return _unit_label(unit, start, cal)
    return f"{start.isoformat()} to {(end - timedelta(days=1)).isoformat()}"


def shift_periods(periods: Sequence[Period], shift: PeriodShift, fiscal_start_month: int) -> list[Period]:
    cal = _Calendar(fiscal_start_month, "fiscal")
    moved = []
    for period in periods:
        start, end = _shift(shift.unit, period.start, shift.offset), _shift(shift.unit, period.end, shift.offset)
        moved.append(Period(label=_period_label(start, end, cal), start=start, end=end))
    return moved


def resolve_time(state: "AgentState", deps: "AgentDeps") -> dict:
    """Graph node: resolve the extracted periods against the deps' reference date.

    A follow-up that names no period of its own moves the previous query's periods instead; with
    neither, there are no periods and ``build_spec`` records the missing period.
    """
    extraction = state["extraction"]
    fiscal_start_month = deps.compiled.pack.business_profile.fiscal_year_start_month
    previous = state.get("previous_spec")
    descriptors = list(extraction.periods)
    if not descriptors:
        # A period option the user picked is applied as it is, without a model reading its label.
        picked = chosen(state.get("choices"), "period")
        if picked and picked[-1] == "all":
            return {"periods": [], "all_time": True}
        if picked and picked[-1] in CHOSEN_PERIODS:
            descriptors = [CHOSEN_PERIODS[picked[-1]]]
    if not descriptors:
        if extraction.previous_periods is not None and previous is not None:
            return {"periods": shift_periods(previous.periods, extraction.previous_periods, fiscal_start_month)}
        # The extraction model can miss a period the question spells out; asking back for it would be wrong.
        descriptors = explicit_periods(state.get("question", ""))
        if not descriptors:
            return {"periods": [], "all_time": says_all_time(state.get("question", ""))}
    try:
        periods = resolve_periods(descriptors, deps.today, fiscal_start_month)
    except TimeResolutionError as error:
        return {"rejection": f"the period cannot be resolved: {error}"}
    return {"periods": periods}
