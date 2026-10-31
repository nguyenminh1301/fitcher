"""Errors that stop or redirect the SQL path, classified for the check node.

- ``policy``: the SQL breaks a rule (guard rejection, access denied); the run
  stops without retrying.
- ``sql``: the SQL is wrong (does not parse, unknown column, type error); the
  error goes back to ``generate_sql`` for another attempt.
- ``runtime``: the query was valid but could not finish (time or memory limit,
  connection failure); it is retried like ``sql``.
"""

from dataclasses import dataclass
from typing import Literal

ErrorCategory = Literal["policy", "sql", "runtime"]


@dataclass(frozen=True)
class AgentError:
    category: ErrorCategory
    node: str
    message: str

    def __str__(self) -> str:
        return f"{self.category} error in {self.node}: {self.message}"
