"""A user's like or dislike of one answer, sent by the web app (DECISIONS §10 and §15)."""

from typing import Literal

from pydantic import Field

from app.contracts.query_spec import ContractModel

MAX_NOTE_LENGTH = 1000


class FeedbackInput(ContractModel):
    # The answer's trace, as its stream events carry it.
    trace_id: str = Field(min_length=1, max_length=64)
    rating: Literal["like", "dislike"]
    note: str = Field(default="", max_length=MAX_NOTE_LENGTH)
