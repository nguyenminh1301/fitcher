"""Load what a question is read against (DECISIONS §6 step 1).

The business profile always; from the conversation, the last ``CONTEXT_TURNS``
turns of its current thread and the latest QuerySpec and result among them,
which a follow-up question or a chart edit builds on. The api reads the
thread before the run starts and passes it in ``deps.history``.
"""

import json

from app.agent.state import AgentDeps, AgentState
from app.contracts.query_spec import QuerySpec
from app.conversation.store import Turn

CONTEXT_TURNS = 6
# Characters of each earlier question and answer a prompt shows.
TURN_TEXT_LIMIT = 300


def load_context(state: AgentState, deps: AgentDeps) -> dict:
    history = list(deps.history[-CONTEXT_TURNS:])
    previous = next((turn for turn in reversed(history) if turn.query_spec is not None), None)
    return {
        "profile": deps.compiled.pack.business_profile,
        "history": history,
        "previous_spec": previous.query_spec if previous else None,
        "previous_result": previous.result if previous else None,
    }


def turn_lines(history: list[Turn]) -> str:
    """The earlier questions and answers for a prompt, one JSON line each, oldest first; never result rows."""
    lines = [
        json.dumps({"question": turn.question[:TURN_TEXT_LIMIT], "answer": turn.answer[:TURN_TEXT_LIMIT]}, ensure_ascii=False)
        for turn in history
    ]
    return "\n".join(lines) or "none"


def spec_json(spec: QuerySpec | None) -> str:
    return json.dumps(spec.model_dump(mode="json", exclude={"warnings"}), ensure_ascii=False) if spec else "none"
