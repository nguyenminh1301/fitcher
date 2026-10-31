"""Result: the typed table returned by a query (DECISIONS §7)."""

from typing import Literal, Self

from pydantic import Field, model_validator

from app.contracts.query_spec import ContractModel

MAX_RESULT_ROWS = 5000

Cell = str | int | float | bool | None


class ColumnInfo(ContractModel):
    name: str = Field(min_length=1)
    type: Literal["string", "number", "date", "datetime", "boolean"]
    role: Literal["dimension", "measure", "time"]
    format: Literal["currency", "count", "ratio", "percent", "days", "number"] | None = None


class Result(ContractModel):
    columns: list[ColumnInfo] = Field(min_length=1)
    rows: list[list[Cell]] = Field(max_length=MAX_RESULT_ROWS)
    row_count: int = Field(ge=0)
    truncated: bool = False

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        names = [column.name for column in self.columns]
        if len(set(names)) != len(names):
            raise ValueError(f"column names must be unique: {names}")
        for position, row in enumerate(self.rows):
            if len(row) != len(self.columns):
                raise ValueError(f"row {position} has {len(row)} cells for {len(self.columns)} columns")
        if self.row_count < len(self.rows):
            raise ValueError(f"row_count {self.row_count} is less than the {len(self.rows)} rows returned")
        if self.truncated and self.row_count <= len(self.rows):
            raise ValueError("a truncated result must have a row_count above the rows returned")
        return self
