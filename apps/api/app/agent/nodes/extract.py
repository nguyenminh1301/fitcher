"""Extract metric, dimension, period and filter terms from the question (DECISIONS §6 step 4).

The ``fast`` alias returns structured terms, never dates or database names;
``resolve_time`` computes dates and ``build_spec`` maps terms to the pack.
Without a router or clarify branch yet, a question with no metric or no period
is refused here, before any SQL is generated.
"""

from pydantic import BaseModel, ConfigDict, Field

from app.agent.nodes.resolve_time import PeriodDescriptor
from app.agent.prompts import render
from app.agent.state import AgentDeps, AgentState, TimeGrain
from app.contracts.query_spec import FilterOp, Scalar
from app.llm.client import LLMError

ALIAS = "fast"
PROMPT = "extract.v1"


class ExtractedFilter(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    column_term: str | None = None
    op: FilterOp = "="
    values: list[Scalar] = Field(min_length=1)


class Extraction(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    metric_terms: list[str] = []
    rank_term: str | None = None
    dimension_terms: list[str] = []
    time_grain: TimeGrain | None = None
    periods: list[PeriodDescriptor] = []
    filters: list[ExtractedFilter] = []
    top_n: int | None = Field(default=None, ge=1)
    compare: bool = False
    language: str = Field(default="en", pattern=r"^[a-z]{2}$")


def extract(state: AgentState, deps: AgentDeps) -> dict:
    try:
        extraction = deps.llm.structured(ALIAS, render(PROMPT, question=state["question"]), Extraction)
    except LLMError as error:
        return {"rejection": f"the question could not be read: {error}"}
    if not extraction.metric_terms and extraction.rank_term is None:
        return {"extraction": extraction, "rejection": "the question names no measure to report"}
    if not extraction.periods:
        return {"extraction": extraction, "rejection": "the question names no period"}
    return {"extraction": extraction, "time_grain": extraction.time_grain}
