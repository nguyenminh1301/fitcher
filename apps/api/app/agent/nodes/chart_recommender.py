"""Choose the chart of an answer (DECISIONS §6 step 15 and §8).

The §8 rules in ``app.agent.chart_rules`` choose from the result and the
QuerySpec. Only when they tie, a bar or a pie for one category and one measure
of at most six non-negative groups, does the ``fast`` alias read the question,
never the rows, to tell whether it asks for a share. An invalid reply or a
gateway failure keeps the rules' pick.
"""

import json

from pydantic import BaseModel, ConfigDict

from app.agent.chart_rules import choose
from app.agent.prompts import render
from app.agent.state import AgentDeps, AgentState
from app.contracts.chart_spec import ChartType
from app.llm.client import LLMError

ALIAS = "fast"
PROMPT = "chart_recommender.v1"


class ChartPick(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    chart_type: ChartType


def chart_recommender(state: AgentState, deps: AgentDeps) -> dict:
    choice = choose(state["result"], state.get("spec"))
    if not choice.tied:
        return {"chart_spec": choice.spec}
    prompt = render(PROMPT, question=json.dumps(state["question"], ensure_ascii=False))
    try:
        pick = deps.llm.structured(ALIAS, prompt, ChartPick).chart_type
    except LLMError:
        pick = None
    return {"chart_spec": choice.drawn_as(pick if pick in choice.tied else None)}
