"""Extract metric, dimension, period and filter terms from the question (DECISIONS §6 step 4).

The ``fast`` alias returns structured terms, never dates or database names;
``resolve_time`` computes dates and ``build_spec`` maps terms to the pack.
In a conversation the prompt also shows the recent turns and the previous
QuerySpec: the alias restates a follow-up as the complete question it means,
and gives its periods as a shift of the previous ones (``previous_periods``)
when it names none. A question that names no measure or no period is not
refused here: ``build_spec`` records what is missing and the gate asks.
"""

import json

from pydantic import BaseModel, ConfigDict, Field

from app.agent.nodes.load_context import spec_json, turn_lines
from app.agent.nodes.resolve_time import PeriodDescriptor, PeriodShift
from app.agent.prompts import render
from app.agent.state import AgentDeps, AgentState, TimeGrain
from app.contracts.query_spec import FilterOp, Scalar
from app.llm.client import LLMError

ALIAS = "fast"
PROMPT = "extract.v3"
# Shown right before the question: the fast alias reads a reply to a clarifying question as the whole
# question unless the instruction to combine them sits next to it.
CONVERSATION = """
Earlier turns (JSON lines, oldest first):
{turns}

Query behind the previous answer:
{spec}

The message below is the user's next message in this conversation. If the assistant's last answer asked the user to choose something, the message is that choice: extract the earlier question with the choice filled in, keeping the earlier question's periods. Otherwise, when a query is shown above and the message names no period of its own, keep or move that query's periods with `previous_periods` and leave `periods` empty.
"""


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
    previous_periods: PeriodShift | None = None


def extract(state: AgentState, deps: AgentDeps) -> dict:
    history = state.get("history", [])
    conversation = CONVERSATION.format(turns=turn_lines(history), spec=spec_json(state.get("previous_spec"))) if history else ""
    try:
        prompt = render(PROMPT, question=json.dumps(state["question"], ensure_ascii=False), conversation=conversation)
        extraction = deps.llm.structured(ALIAS, prompt, Extraction)
    except LLMError as error:
        return {"rejection": f"the question could not be read: {error}"}
    return {"extraction": extraction, "time_grain": extraction.time_grain}
