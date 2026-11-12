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

from app.contracts.admin import AuditRow, CostRow, RunRow, RunTrace  # noqa: E402 - needs apps/api on the path
from app.contracts.admin_feedback import FeedbackRow, ProposalResult  # noqa: E402
from app.contracts.chart_spec import ChartSpec  # noqa: E402
from app.contracts.conversations import (  # noqa: E402
    Conversation, ConversationGroup, ConversationPatch, ConversationThread, GroupInput,
)
from app.contracts.documents import DocumentList, DocumentRolesChange, DocumentView, DraftResult  # noqa: E402
from app.contracts.evaluation import EvalReportView, EvalRunStarted  # noqa: E402
from app.contracts.events import AskEvent, AskRequest  # noqa: E402
from app.contracts.feedback import FeedbackInput  # noqa: E402
from app.contracts.model_tiers import ModelTierChange, ModelTiers  # noqa: E402
from app.contracts.query_spec import QuerySpec  # noqa: E402
from app.contracts.result import Result  # noqa: E402
from app.contracts.review import DatasetView, ReviewItem, ReviewItemPatch  # noqa: E402
from app.contracts.setup import SetupModeChange, SetupStatus  # noqa: E402
from app.contracts.users import UserRoles, UserView  # noqa: E402

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
    "model_tiers": (ModelTiers, "serialization"),
    "model_tier_change": (ModelTierChange, "validation"),
    "dataset_view": (DatasetView, "serialization"),
    "review_item": (ReviewItem, "serialization"),
    "review_item_patch": (ReviewItemPatch, "validation"),
    "document_view": (DocumentView, "serialization"),
    "document_list": (DocumentList, "serialization"),
    "document_roles_change": (DocumentRolesChange, "validation"),
    "draft_result": (DraftResult, "serialization"),
    "run_row": (RunRow, "serialization"),
    "run_trace": (RunTrace, "serialization"),
    "audit_row": (AuditRow, "serialization"),
    "cost_row": (CostRow, "serialization"),
    "feedback_row": (FeedbackRow, "serialization"),
    "proposal_result": (ProposalResult, "serialization"),
    "eval_report_view": (EvalReportView, "serialization"),
    "eval_run_started": (EvalRunStarted, "serialization"),
    "user_view": (UserView, "serialization"),
    "user_roles": (UserRoles, "validation"),
    "setup_status": (SetupStatus, "serialization"),
    "setup_mode_change": (SetupModeChange, "validation"),
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
