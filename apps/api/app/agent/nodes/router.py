"""Classify each question by intent (DECISIONS §6 step 2).

The ``fast`` alias reads the question, the conversation's recent questions and
answers and the previous QuerySpec, never result rows, and returns one of four
intents with its confidence and the question's language. An invalid reply or
a confidence below ``MIN_CONFIDENCE`` assumes ``data_query``: extraction then
either reads the question as a data question or refuses it before any SQL.
"""

import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.agent.nodes.load_context import spec_json, turn_lines
from app.agent.prompts import render
from app.agent.state import AgentDeps, AgentState
from app.llm.client import LLMError

ALIAS = "fast"
PROMPT = "router.v1"
MIN_CONFIDENCE = 0.5

Intent = Literal["data_query", "metadata_qa", "chart_edit", "out_of_scope"]


class Routing(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    intent: Intent
    confidence: float = Field(ge=0, le=1)
    language: str = Field(pattern=r"^[a-z]{2}$")


def router(state: AgentState, deps: AgentDeps) -> dict:
    profile = deps.compiled.pack.business_profile
    prompt = render(
        PROMPT,
        industry=profile.industry,
        datasets="\n".join(f"- {dataset.description}" for dataset in deps.compiled.pack.datasets.datasets),
        history=turn_lines(state.get("history", [])),
        previous_spec=spec_json(state.get("previous_spec")),
        question=json.dumps(state["question"], ensure_ascii=False),
    )
    try:
        routing = deps.llm.structured(ALIAS, prompt, Routing)
    except LLMError:
        routing = None
    if routing is None or routing.confidence < MIN_CONFIDENCE:
        return {"intent": "data_query", "intent_fallback": True, "language": None}
    return {"intent": routing.intent, "intent_fallback": False, "language": routing.language}
