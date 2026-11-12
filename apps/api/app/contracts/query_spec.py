"""QuerySpec: the validated, pack-resolved description of one data question.

The shape is fixed by DECISIONS §7. ``build_spec`` produces it from the
extraction and retrieval, and ``generate_sql`` turns it into SQL; nothing
downstream reads the user's raw question for data decisions.
"""

from datetime import date
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

MAX_TOP_N = 1000

Scalar = str | int | float | bool
FilterOp = Literal["=", "!=", "<", "<=", ">", ">=", "in", "not in"]
LIST_OPS = frozenset({"in", "not in"})


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Period(ContractModel):
    """A labelled half-open date range ``[start, end)``."""

    label: str = Field(min_length=1)
    start: date
    end: date

    @model_validator(mode="after")
    def _half_open(self) -> Self:
        if self.start >= self.end:
            raise ValueError(f"period {self.label!r}: start {self.start} must be before end {self.end}")
        return self


class Filter(ContractModel):
    column: str = Field(min_length=1)
    op: FilterOp
    value: Scalar | list[Scalar]

    @model_validator(mode="after")
    def _value_matches_op(self) -> Self:
        is_list = isinstance(self.value, list)
        if self.op in LIST_OPS and (not is_list or not self.value):
            raise ValueError(f"filter on {self.column!r}: '{self.op}' needs a non-empty list of values")
        if self.op not in LIST_OPS and is_list:
            raise ValueError(f"filter on {self.column!r}: '{self.op}' needs a single value")
        return self


class QuerySpec(ContractModel):
    intent: Literal["data_query"] = "data_query"
    metric_ids: list[str] = Field(min_length=1)
    dimensions: list[str] = []
    periods: list[Period] = Field(min_length=1)
    filters: list[Filter] = []
    top_n: int | None = Field(default=None, ge=1, le=MAX_TOP_N)
    rank_by: str | None = None
    rank_period: str | None = None
    compare: bool = False
    dataset: str = Field(min_length=1)
    warnings: list[str] = []

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        labels = [period.label for period in self.periods]
        if len(set(labels)) != len(labels):
            raise ValueError(f"period labels must be unique: {labels}")
        if self.rank_by is not None and self.rank_by not in self.metric_ids:
            raise ValueError(f"rank_by {self.rank_by!r} must be one of metric_ids {self.metric_ids}")
        if self.rank_period is not None and self.rank_period not in labels:
            raise ValueError(f"rank_period {self.rank_period!r} must be one of the period labels {labels}")
        if self.compare and len(self.periods) < 2:
            raise ValueError("compare needs at least two periods")
        return self
