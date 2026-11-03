"""Load what a question is read against (DECISIONS §6 step 1).

The business profile always; from the conversation, the last ``CONTEXT_TURNS``
turns of its current thread and the latest QuerySpec and result among them,
which a follow-up question or a chart edit builds on. The api reads the
thread before the run starts and passes it in ``deps.history``.
"""

from app.agent.state import AgentDeps, AgentState

CONTEXT_TURNS = 6


def load_context(state: AgentState, deps: AgentDeps) -> dict:
    history = list(deps.history[-CONTEXT_TURNS:])
    previous = next((turn for turn in reversed(history) if turn.query_spec is not None), None)
    return {
        "profile": deps.compiled.pack.business_profile,
        "history": history,
        "previous_spec": previous.query_spec if previous else None,
        "previous_result": previous.result if previous else None,
    }
