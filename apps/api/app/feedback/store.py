"""Read runs and write proposals in ``agent_logs`` (Phase 12).

The api reads as ``agent_logs_review_reader`` and writes as the insert-only
``agent_logs_writer``; ``jobs.propose_examples`` uses the admin connection for
both. A run's QuerySpec comes from its ``build_spec`` event, its SQL from the
last ``sql_runs`` attempt and its rating and note from the latest feedback.
"""

from collections.abc import Mapping
from dataclasses import asdict
from datetime import UTC, datetime
import json
import os

import clickhouse_connect

from app.contracts.admin_feedback import FeedbackRow
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
        # Shared across concurrent requests: a session would serialize them and refuse overlaps.
        autogenerate_session_id=False,
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

    def proposals(self, pack: str, open_only: bool = True) -> list[Proposal]:
        """The latest version of each proposal of the pack; with ``open_only`` only those still to review."""
        # The whole latest row as one tuple, so no aggregate refers to an alias of another.
        sql = (f"SELECT argMax(tuple({', '.join(COLUMNS)}), ts) AS latest FROM {TABLE} "
               "WHERE pack = {pack:String} GROUP BY proposal_id ORDER BY max(ts) DESC")
        found = []
        for (latest,) in self._reader.query(sql, parameters={"pack": pack}).result_rows:
            row = dict(zip(COLUMNS, latest, strict=True))
            row["ts"] = row["ts"] if row["ts"].tzinfo else row["ts"].replace(tzinfo=UTC)
            found.append(Proposal(**row))
        return [p for p in found if p.status == "proposed"] if open_only else found

    def feedback(self, pack: str, rating: str | None, start: datetime | None, end: datetime | None) -> list[FeedbackRow]:
        """Likes and dislikes of the pack's answers, newest first, with the run's status and any proposal."""
        where, parameters = ["r.pack = {pack:String}"], {"pack": pack}
        if rating:
            where.append("f.rating = {rating:String}")
            parameters["rating"] = rating
        if start:
            where.append("f.ts >= {start:DateTime64(3)}")
            parameters["start"] = start
        if end:
            where.append("f.ts < {end:DateTime64(3)}")
            parameters["end"] = end
        sql = (
            "SELECT f.trace_id, f.ts, f.user_id, f.rating, r.question, f.note, r.status, p.status "
            "FROM agent_logs.feedback AS f "
            "INNER JOIN (SELECT * FROM agent_logs.runs FINAL) AS r ON r.trace_id = f.trace_id "
            f"LEFT JOIN (SELECT trace_id, argMax(status, ts) AS status FROM {TABLE} GROUP BY trace_id) AS p "
            "ON p.trace_id = f.trace_id "
            f"WHERE {' AND '.join(where)} ORDER BY f.ts DESC LIMIT 500"
        )
        return [
            FeedbackRow(trace_id=trace_id, ts=ts, user_id=user_id, rating=rating_value, question=question,
                        note=note or None, run_status=run_status, proposal=proposal or None)
            for trace_id, ts, user_id, rating_value, question, note, run_status, proposal
            in self._reader.query(sql, parameters=parameters).result_rows
        ]

    def save(self, proposal: Proposal) -> None:
        row = asdict(proposal)
        self._writer.insert(TABLE, [[row[column] for column in COLUMNS]], column_names=list(COLUMNS))
