"""The fake chat client node tests use, without network access."""

from fake_llm import FakeLLMClient
from pydantic import BaseModel
import pytest

from app.llm.client import Prompt


class Answer(BaseModel):
    word: str
    count: int


PROMPT = Prompt(system="Reply in JSON.", user="Say ready twice")


def test_fake_client_records_calls_and_checks_tiers():
    fake = FakeLLMClient([{"word": "a", "count": 1}, "plain"])

    assert fake.structured("fast", PROMPT, Answer) == Answer(word="a", count=1)
    assert fake.text("sql-gen-hard", PROMPT) == "plain"
    assert [(call.method, call.tier, call.prompt) for call in fake.calls] == [
        ("structured", "fast", PROMPT.text), ("text", "sql-gen-hard", PROMPT.text),
    ]
    assert (fake.calls[0].system, fake.calls[0].user) == ("Reply in JSON.", "Say ready twice")
    with pytest.raises(ValueError):
        fake.text("gpt-5.4", PROMPT)
