"""Every ClickHouse client the api shares across requests must allow concurrent queries.

clickhouse-connect binds a client to one server session by default, and ClickHouse refuses two
queries of one session at once; the console loads conversations and groups in parallel.
"""

import clickhouse_connect
import pytest

from app.admin.logs import trace_reader_client
from app.conversation.store import conversations_client
from app.feedback.store import review_reader_client
from app.llm.model_store import model_tiers_client
from app.observability.log_writer import writer_client
from app.onboarding.documents import pack_review_client

ENV = {name: "secret" for name in (
    "CLICKHOUSE_CONVERSATIONS_PASSWORD", "CLICKHOUSE_MODEL_TIERS_PASSWORD", "CLICKHOUSE_PACK_REVIEW_PASSWORD",
    "CLICKHOUSE_TRACE_READER_PASSWORD", "CLICKHOUSE_REVIEW_READER_PASSWORD", "CLICKHOUSE_LOGS_WRITER_PASSWORD",
)}


@pytest.mark.parametrize("factory", [
    conversations_client, model_tiers_client, pack_review_client, trace_reader_client, review_reader_client,
    writer_client,
])
def test_shared_clients_open_no_session(monkeypatch, factory):
    seen = {}
    monkeypatch.setattr(clickhouse_connect, "get_client", lambda **kwargs: seen.update(kwargs) or object())
    factory(ENV)
    assert seen.get("autogenerate_session_id") is False
