"""Write the JSON Schemas of the backend contracts the web app uses (DECISIONS §7).

Run with ``uv run --project apps/api python scripts/generate_contract_types.py``,
then ``npm --prefix apps/web run contracts:generate`` to turn the schemas into
TypeScript under ``apps/web/lib/contracts/``. Tests on both sides fail while a
committed schema or type differs from what these produce.
"""

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from app.contracts.chart_spec import ChartSpec  # noqa: E402 - needs apps/api on the path
from app.contracts.conversations import (  # noqa: E402
    Conversation, ConversationGroup, ConversationPatch, ConversationThread, GroupInput,
)
from app.contracts.events import AskEvent, AskRequest  # noqa: E402
from app.contracts.feedback import FeedbackInput  # noqa: E402
from app.contracts.query_spec import QuerySpec  # noqa: E402
from app.contracts.result import Result  # noqa: E402

# Each contract with the JSON Schema mode of its direction: what the api accepts ("validation") or
# what it sends ("serialization", where every field is present).
CONTRACTS = {
    "query_spec": (QuerySpec, "validation"),
    "result": (Result, "validation"),
    "chart_spec": (ChartSpec, "validation"),
    "ask_request": (AskRequest, "validation"),
    "ask_event": (AskEvent, "serialization"),
    "conversation": (Conversation, "serialization"),
    "conversation_group": (ConversationGroup, "serialization"),
    "conversation_thread": (ConversationThread, "serialization"),
    "conversation_patch": (ConversationPatch, "validation"),
    "group_input": (GroupInput, "validation"),
    "feedback_input": (FeedbackInput, "validation"),
}
SCHEMAS = ROOT / "apps" / "web" / "lib" / "contracts" / "schemas"


def main() -> int:
    SCHEMAS.mkdir(parents=True, exist_ok=True)
    for name, (model, mode) in CONTRACTS.items():
        text = json.dumps(model.model_json_schema(mode=mode), indent=2, ensure_ascii=False) + "\n"
        (SCHEMAS / f"{name}.schema.json").write_text(text, encoding="utf-8", newline="\n")
        print(f"Wrote {name}.schema.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
