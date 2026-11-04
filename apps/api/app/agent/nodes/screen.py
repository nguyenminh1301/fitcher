"""Screen the question before any LLM call (DECISIONS §9, Layer 0).

The first graph node. It screens the new question, writes one
``agent_logs.input_screening`` row and records the verdict as the run's
``screening`` gateway metadata: ``flag`` for a flag, and for a block that log
mode lets through, ``allow`` otherwise. The run stops with the ``blocked``
reply when screening is unavailable, in both modes, or when it blocks the
question in enforce mode. History is not screened again: every stored turn was
screened when it was asked, and a blocked question is never stored.

The reply is written in the question's language, read from its letters
because the router has not run yet, and never repeats the question.
"""

import re

from app.agent.state import AgentDeps, AgentState, BlockedReason
from app.observability.events import InputScreeningRecord, utc_now
from app.observability.tracing import current_run
from app.screening.rules import RULES_VERSION
from app.screening.screen import Verdict, stops_run

SOURCE = "question"

# Letters only Vietnamese uses among the two languages the replies are written in.
_VIETNAMESE = re.compile(
    "[ăâđêôơưàáảãạằắẳẵặầấẩẫậèéẻẽẹềếểễệìíỉĩịòóỏõọồốổỗộờớởỡợùúủũụừứửữựỳýỷỹỵ]", re.IGNORECASE,
)

MESSAGES: dict[BlockedReason, dict[str, str]] = {
    "screened": {
        "en": "This question can't be answered because it reads like an attempt to change the assistant's "
              "instructions. Ask about your data in your own words.",
        "vi": "Không thể trả lời câu hỏi này vì nó giống một yêu cầu thay đổi chỉ dẫn của trợ lý. "
              "Hãy hỏi về dữ liệu của bạn bằng lời của chính bạn.",
    },
    "unavailable": {
        "en": "Questions can't be answered right now because the safety check on questions is unavailable. "
              "Try again later or ask an admin.",
        "vi": "Hiện chưa thể trả lời câu hỏi vì bước kiểm tra an toàn câu hỏi đang không hoạt động. "
              "Hãy thử lại sau hoặc báo quản trị viên.",
    },
    "gateway": {
        "en": "This answer was stopped because content sent to the language model failed the safety check. "
              "Ask about your data in other words.",
        "vi": "Câu trả lời đã bị dừng vì nội dung gửi tới mô hình ngôn ngữ không qua được bước kiểm tra an toàn. "
              "Hãy hỏi về dữ liệu của bạn theo cách khác.",
    },
}


def language_of(text: str) -> str:
    return "vi" if _VIETNAMESE.search(text) else "en"


def blocked_message(reason: BlockedReason, lang: str) -> str:
    return MESSAGES[reason]["vi" if lang == "vi" else "en"]


def screen(state: AgentState, deps: AgentDeps) -> dict:
    question = state["question"]
    if deps.screener is None:
        verdict = Verdict(verdict="unavailable", score=None, rule_hits=[], model_version=RULES_VERSION)
    else:
        verdict = deps.screener.screen(question, SOURCE)
    if deps.logs is not None:
        deps.logs.enqueue(InputScreeningRecord(
            trace_id=state["trace_id"], ts=utc_now(), user_id=deps.user_id, source=SOURCE, verdict=verdict.verdict,
            mode=deps.screen_mode, score=verdict.score, rule_hits=verdict.rule_hits, model_version=verdict.model_version,
        ))
    if stops_run(verdict, deps.screen_mode):
        reason: BlockedReason = "unavailable" if verdict.verdict == "unavailable" else "screened"
        return {"screening": verdict, "blocked": reason, "language": language_of(question)}
    if run := current_run():
        run.screening = "allow" if verdict.verdict == "allow" else "flag"
    return {"screening": verdict, "blocked": None}
