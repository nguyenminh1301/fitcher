"""The billable smoke job over the gateway, with the SDK call faked: one call per mapped model."""

import litellm
import pytest

from jobs import smoke_llm

from app.llm.providers import ProviderStore
from app.llm.routes import fill_defaults, TierMapping
from app.state.db import shared_state
from app.state.secrets import shared_vault

KEY = "sk-test-smoke-key-4040"


def chat(content: str) -> litellm.ModelResponse:
    return litellm.ModelResponse(choices=[{"message": {"role": "assistant", "content": content}, "index": 0}])


class Sdk:
    """Answers chat calls with ``reply`` and embedding calls with one vector; records each model called."""

    def __init__(self, reply=None, fail_model: str | None = None):
        self.reply = reply or chat('{"word": "ready", "count": 2}')
        self.fail_model = fail_model
        self.models: list[str] = []

    def completion(self, **kwargs):
        self.models.append(kwargs["model"])
        if kwargs["model"] == self.fail_model:
            raise litellm.AuthenticationError(f"bad key {KEY}", "openai", kwargs["model"])
        return self.reply

    def embedding(self, **kwargs):
        self.models.append(kwargs["model"])
        return litellm.EmbeddingResponse(data=[{"object": "embedding", "index": 0, "embedding": [0.1] * kwargs["dimensions"]}])


@pytest.fixture
def configured():
    store = ProviderStore(shared_state(), shared_vault())
    mapping = TierMapping(shared_state(), store)
    fill_defaults(mapping, store.create("openai", api_key=KEY), dimensions=8)
    mapping.set_embedding("openai", "text-embedding-3-large", 8)


def run(sdk: Sdk, *argv: str) -> int:
    return smoke_llm.main(list(argv), completion=sdk.completion, embedding=sdk.embedding)


def test_every_mapped_model_gets_one_structured_or_embedding_call(configured, capsys):
    sdk = Sdk()

    assert run(sdk) == 0

    assert sdk.models == ["openai/gpt-5.4-mini", "openai/gpt-5.4", "openai/gpt-5.5", "openai/text-embedding-3-large"]
    out = capsys.readouterr().out
    assert "fast, sql-small: openai/gpt-5.4-mini ok" in out
    assert "embed: openai/text-embedding-3-large ok" in out


def test_tier_limits_the_calls(configured):
    sdk = Sdk()

    assert run(sdk, "--tier", "sql-gen") == 0

    assert sdk.models == ["openai/gpt-5.4"]


def test_a_reply_that_breaks_the_schema_fails_without_printing_it(configured, capsys):
    assert run(Sdk(reply=chat('{"word": "private-reply"}')), "--tier", "fast") == 1

    err = capsys.readouterr().err
    assert "FAIL" in err and "private-reply" not in err


def test_a_provider_error_fails_without_the_key(configured, capsys):
    assert run(Sdk(fail_model="openai/gpt-5.4"), "--tier", "sql-gen") == 1

    err = capsys.readouterr().err
    assert "AuthenticationError" in err and KEY not in err


def test_without_a_provider_there_is_nothing_to_check(capsys):
    assert run(Sdk()) == 1
    assert "add a provider" in capsys.readouterr().err


def test_an_unknown_tier_is_refused(configured):
    with pytest.raises(SystemExit):
        run(Sdk(), "--tier", "huge")



def test_a_local_embedding_model_is_run_instead_of_called(monkeypatch, capsys):
    store = ProviderStore(shared_state(), shared_vault())
    fill_defaults(TierMapping(shared_state(), store), store.create("openai", api_key=KEY), dimensions=8)
    ran: list[list[str]] = []

    class Local:
        dimensions = 384

        def embed(self, texts):
            ran.append(list(texts))
            return [[0.0] * 384]

    monkeypatch.setattr(smoke_llm.clients, "embedding_client", lambda dimensions, **kwargs: Local())
    sdk = Sdk()

    assert run(sdk, "--tier", "embed") == 0

    assert ran == [["ready"]] and sdk.models == []
    assert "embed: local/sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2 ok" in capsys.readouterr().out
