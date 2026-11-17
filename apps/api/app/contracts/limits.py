"""The ``limits`` settings group: how many questions the api answers at once (app/api/limits.py)."""

from pydantic import Field

from app.contracts.query_spec import ContractModel


class LimitSettings(ContractModel):
    concurrent_questions: int = Field(ge=1, le=64)
