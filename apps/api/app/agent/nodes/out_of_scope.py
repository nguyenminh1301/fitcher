"""Reply briefly to a question the assistant does not answer (DECISIONS §6 step 3).

The ``fast`` alias writes one or two sentences in the question's language
saying what the assistant can answer; no SQL is generated. When the gateway
fails, a fixed reply in the question's language, or English, is used.
"""

import json

from app.agent.prompts import render
from app.agent.state import AgentDeps, AgentState
from app.llm.client import LLMError

ALIAS = "fast"
PROMPT = "out_of_scope.v2"
FALLBACK = {
    "en": "I can only answer questions about the company's data, such as figures, rankings and trends. Try asking about one of those.",
    "vi": "Mình chỉ trả lời được các câu hỏi về dữ liệu của công ty, như số liệu, xếp hạng và xu hướng. Bạn thử hỏi về một trong những điều đó nhé.",
}


def out_of_scope(state: AgentState, deps: AgentDeps) -> dict:
    language = state.get("language") or "en"
    prompt = render(
        PROMPT,
        language=language,
        industry=deps.compiled.pack.business_profile.industry,
        question=json.dumps(state["question"], ensure_ascii=False),
    )
    try:
        return {"reply": deps.llm.text(ALIAS, prompt).strip()}
    except LLMError:
        return {"reply": FALLBACK.get(language, FALLBACK["en"])}
