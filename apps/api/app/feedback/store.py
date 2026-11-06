"""Read runs and write proposals in ``agent_logs`` (Phase 12).

The api reads as ``agent_logs_review_reader`` and writes as the insert-only
``agent_logs_writer``; ``jobs.propose_examples`` uses the admin connection for
both. A run's QuerySpec comes from its ``build_spec`` event, its SQL from the
last ``sql_runs`` attempt and its rating and note from the latest feedback.
"""

from collections.abc import Mapping
from dataclasses import asdict
from datetime import datetime
import json
import os

import clickhouse_connect

from app.feedback.proposals import Proposal, RunFacts, normalize

TABLE = "agent_logs.example_proposals"
COLUMNS = ("proposal_id", "pack", "ts", "trace_id", "question", "sql", "source", "status", "spec", "error", "note",
           "confidence")
FACTS = """
SELECT r.trace_id, r.pack, r.question, r.status, r.intent, r.error, e.spec, s.sql, f.rating, f.note
FROM agent_logs.runs AS r FINAL
LEFT JOIN (
    SELECT trace_id, argMax(JSONExtractRaw(payload, 'spec'), ts) AS spec
    FROM agent_logs.events WHERE node = 'build_spec' GROUP BY trace_id
) AS e ON e.trace_id = r.trace_id
LEFT JOIN (SELECT trace_id, argMax(sql, attempt) AS sql FROM agent_logs.sql_runs GROUP BY trace_id) AS s
    ON s.trace_id = r.trace_id
LEFT JOIN (
    SELECT trace_id, argMax(rating, ts) AS rating, argMax(note, ts) AS note FROM agent_logs.feedback GROUP BY trace_id
) AS f ON f.trace_id = r.trace_id
WHERE r.pack = {pack:String}"""


def review_reader_client(env: Mapping[str, str] | None = None):
    env = os.environ if env is None else env
    password = env.get("CLICKHOUSE_REVIEW_READER_PASSWORD", "")
    if not password:
        raise RuntimeError("CLICKHOUSE_REVIEW_READER_PASSWORD must be set")
    return clickhouse_connect.get_client(
        host=env.get("CLICKHOUSE_HOST", "clickhouse"), port=int(env.get("CLICKHOUSE_HTTP_PORT", "8123")),
        username="agent_logs_review_reader", password=password,
    )


def _facts(row) -> RunFacts:
    trace_id, pack, question, status, intent, error, spec, sql, rating, note = row
    try:
        parsed = json.loads(spec) if spec else None
    except ValueError:
        parsed = None
    return RunFacts(trace_id=trace_id, pack=pack, question=question, status=status, intent=intent, error=error or "",
                    spec=parsed if isinstance(parsed, dict) else None, sql=sql or "", rating=rating or None,
                    note=note or "")


class ClickHouseProposalStore:
    def __init__(self, reader, writer):
        self._reader = reader
        self._writer = writer

    def candidates(self, pack: str, since: datetime) -> list[RunFacts]:
        sql = FACTS + "\n  AND r.ts >= {since:DateTime64(3)}\nORDER BY r.ts"
        return [_facts(row) for row in self._reader.query(sql, parameters={"pack": pack, "since": since}).result_rows]

    def run(self, pack: str, trace_id: str) -> RunFacts | None:
        rows = self._reader.query(FACTS + "\n  AND r.trace_id = {trace_id:String}",
                                  parameters={"pack": pack, "trace_id": trace_id}).result_rows
        return _facts(rows[0]) if rows else None

    def known_questions(self, pack: str) -> set[str]:
        rows = self._reader.query(f"SELECT question FROM {TABLE} WHERE pack = {{pack:String}}",
                                  parameters={"pack": pack}).result_rows
        return {normalize(question) for (question,) in rows}

    def save(self, proposal: Proposal) -> None:
        row = asdict(proposal)
        self._writer.insert(TABLE, [[row[column] for column in COLUMNS]], column_names=list(COLUMNS))
