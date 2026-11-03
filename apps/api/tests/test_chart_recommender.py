"""chart_recommender: the §8 rules choose, and the fast alias reads the question only when a bar and a pie tie."""

from agent_fixtures import deps
import pytest
from test_chart_rules import MONTHLY, SHARE

from app.agent.nodes.chart_recommender import chart_recommender
from app.llm.client import LLMError

QUESTION = "What share of widget revenue does each region bring?"


def recommend(data, replies):
    agent = deps(replies)
    return chart_recommender({"question": QUESTION, "result": data, "spec": None}, agent)["chart_spec"], agent.llm.calls


def test_a_tie_asks_the_fast_alias_with_the_question_and_never_the_rows():
    spec, calls = recommend(SHARE, [{"chart_type": "pie"}])

    assert spec.type == "pie"
    assert [(call.alias, call.method) for call in calls] == [("fast", "structured")]
    assert QUESTION in calls[0].prompt and "North" not in calls[0].prompt


@pytest.mark.parametrize("reply", [LLMError("gateway down"), {"chart_type": "line"}], ids=["gateway failure", "type outside the tie"])
def test_a_tie_keeps_the_bar_when_the_reply_cannot_be_used(reply):
    spec, _ = recommend(SHARE, [reply])

    assert spec.type == "bar"


def test_a_chart_the_rules_settle_calls_no_llm():
    spec, calls = recommend(MONTHLY, [])

    assert (spec.type, calls) == ("line", [])
