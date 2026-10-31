"""Summarize the returned rows in the question's language (DECISIONS §6 step 16).

The ``fast`` alias sees only the question, the spec and the returned rows;
every figure it may quote is already a column computed in SQL.
"""

import json

from app.agent.prompts import render
from app.agent.state import AgentDeps, AgentState
from app.llm.client import LLMError

ALIAS = "fast"
PROMPT = "summarize.v1"
ROWS_IN_PROMPT = 200


def summarize(state: AgentState, deps: AgentDeps) -> dict:
    result = state["result"]
    rows = result.rows[:ROWS_IN_PROMPT]
    prompt = render(
        PROMPT,
        language=state["extraction"].language,
        question=state["question"],
        spec=json.dumps(state["spec"].model_dump(mode="json", exclude={"warnings"}), ensure_ascii=False),
        warnings="\n".join(f"- {warning}" for warning in state.get("warnings", [])) or "none",
        columns=", ".join(f"{column.name} ({column.role}{', ' + column.format if column.format else ''})" for column in result.columns),
        shown=str(len(rows)),
        row_count=str(result.row_count),
        rows="\n".join(json.dumps(row, ensure_ascii=False) for row in rows) or "no rows",
    )
    try:
        return {"summary": deps.llm.text(ALIAS, prompt).strip()}
    except LLMError as error:
        return {"summary": None, "warnings": [*state.get("warnings", []), f"no summary: {error}"]}
