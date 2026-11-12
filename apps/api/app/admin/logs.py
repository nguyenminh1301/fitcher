"""Read ``agent_logs`` for the console's admin sections (DECISIONS §10, §15).

``AdminLogs`` runs parameterized SELECTs as ``agent_logs_trace_reader``, the
read-only user whose profile caps execution time and result rows. Runs and
audit rows are those of the active pack; conversations include the ones their
owner deleted, which only an admin may read. Costs are LiteLLM's estimates.
"""

from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime
import os
from typing import Protocol

import clickhouse_connect

from app.contracts.admin import (
    AdminConversation, AdminConversationThread, AdminMessage, AuditRow, CostRow, RunRow, RunTrace, ScreeningRow,
    TraceItem,
)
from app.llm.tiers import provider_of

PAGE_SIZE = 50
TEXT_LIMIT = 300


class Query(Protocol):
    def __call__(self, sql: str, parameters: dict) -> Sequence[Sequence]:
        """Rows of one parameterized SELECT."""


def trace_reader_client(env: Mapping[str, str] | None = None):
    env = os.environ if env is None else env
    password = env.get("CLICKHOUSE_TRACE_READER_PASSWORD", "")
    if not password:
        raise RuntimeError("CLICKHOUSE_TRACE_READER_PASSWORD must be set")
    return clickhouse_connect.get_client(
        host=env.get("CLICKHOUSE_HOST", "clickhouse"), port=int(env.get("CLICKHOUSE_HTTP_PORT", "8123")),
        username="agent_logs_trace_reader", password=password,
        # Shared across concurrent requests: a session would serialize them and refuse overlaps.
        autogenerate_session_id=False,
    )


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _short(value: object) -> str:
    return " ".join(str(value or "").split())[:TEXT_LIMIT]


RUN_SELECT = """
SELECT r.trace_id, r.ts, r.user_id, a.role, r.question, r.intent, r.status, r.latency_ms, c.cost, r.error
FROM agent_logs.runs AS r FINAL
LEFT JOIN (SELECT trace_id, any(role) AS role FROM agent_logs.audit GROUP BY trace_id) AS a ON a.trace_id = r.trace_id
LEFT JOIN (SELECT trace_id, sum(cost_usd) AS cost FROM agent_logs.llm_calls GROUP BY trace_id) AS c
    ON c.trace_id = r.trace_id
WHERE r.pack = {pack:String}"""


class AdminLogs:
    def __init__(self, query: Query, pack: str):
        self.query = query
        self.pack = pack

    @classmethod
    def from_client(cls, client, pack: str) -> "AdminLogs":
        return cls(lambda sql, parameters: client.query(sql, parameters=parameters).result_rows, pack)

    @staticmethod
    def _run(row: Sequence) -> RunRow:
        trace_id, ts, user_id, role, question, intent, status, latency_ms, cost, error = row
        return RunRow(
            trace_id=trace_id, ts=_aware(ts), user_id=user_id, role=role or "", question=question, intent=intent,
            status=status, latency_ms=int(latency_ms or 0), cost_usd=round(float(cost or 0.0), 6), error=error or "",
        )

    def runs(
        self, *, user: str | None = None, start: date | None = None, end: date | None = None,
        status: str | None = None, page: int = 1,
    ) -> list[RunRow]:
        """Runs newest first, ``PAGE_SIZE`` per page; ``end`` is exclusive."""
        where, parameters = [], {"pack": self.pack, "limit": PAGE_SIZE, "offset": (max(page, 1) - 1) * PAGE_SIZE}
        if user:
            where.append("r.user_id = {user:String}")
            parameters["user"] = user
        if start:
            where.append("r.ts >= {start:Date}")
            parameters["start"] = start
        if end:
            where.append("r.ts < {end:Date}")
            parameters["end"] = end
        if status:
            where.append("r.status = {status:String}")
            parameters["status"] = status
        sql = RUN_SELECT + "".join(f"\n  AND {clause}" for clause in where)
        sql += "\nORDER BY r.ts DESC\nLIMIT {limit:UInt32} OFFSET {offset:UInt32}"
        return [self._run(row) for row in self.query(sql, parameters)]

    def trace(self, trace_id: str) -> RunTrace | None:
        rows = self.query(RUN_SELECT + "\n  AND r.trace_id = {trace_id:String}", {"pack": self.pack, "trace_id": trace_id})
        if not rows:
            return None
        parameters = {"trace_id": trace_id}
        items: list[tuple[datetime, TraceItem]] = []
        for ts, node, status, duration_ms in self.query(
            "SELECT ts, node, status, duration_ms FROM agent_logs.events WHERE trace_id = {trace_id:String} ORDER BY ts",
            parameters,
        ):
            items.append((_aware(ts), TraceItem(
                name=node, kind="node", status="ok" if status == "ok" else "err", ms=int(duration_ms or 0),
            )))
        for ts, node, alias, provider, model, tokens, cost, latency_ms, status, error in self.query(
            "SELECT ts, node, alias, provider, model, total_tokens, cost_usd, latency_ms, status, error "
            "FROM agent_logs.llm_calls WHERE trace_id = {trace_id:String} ORDER BY ts",
            parameters,
        ):
            items.append((_aware(ts), TraceItem(
                name=f"LLM {node}", kind="llm", status="ok" if status in ("ok", "success") else "err",
                ms=int(latency_ms or 0),
                meta=[alias or provider, model, f"{int(tokens or 0)} tokens", "no price" if cost is None else f"${float(cost):.6f}"],
                error=_short(error) or None,
            )))
        for ts, attempt, sql, rows_read, error in self.query(
            "SELECT ts, attempt, sql, rows, error FROM agent_logs.sql_runs WHERE trace_id = {trace_id:String} ORDER BY ts",
            parameters,
        ):
            items.append((_aware(ts), TraceItem(
                name=f"SQL attempt {attempt}", kind="sql", status="err" if error else "ok",
                meta=[f"{int(rows_read or 0)} rows"], sql=sql, error=_short(error) or None,
            )))
        for ts, role, decision, dataset, reason in self.query(
            "SELECT ts, role, decision, dataset, reason FROM agent_logs.audit WHERE trace_id = {trace_id:String} ORDER BY ts",
            parameters,
        ):
            items.append((_aware(ts), TraceItem(
                name=f"Access {dataset}", kind="access", status="deny" if decision == "DENY" else "ok",
                meta=[role, decision], error=_short(reason) or None,
            )))
        items.sort(key=lambda pair: pair[0])
        return RunTrace(run=self._run(rows[0]), items=[item for _, item in items])

    def audit(self, *, decision: str | None = None, page: int = 1) -> list[AuditRow]:
        sql = (
            "SELECT a.ts, a.trace_id, a.user_id, a.role, a.decision, a.dataset, a.blocked_tables, a.reason "
            "FROM agent_logs.audit AS a WHERE a.trace_id IN "
            "(SELECT trace_id FROM agent_logs.runs WHERE pack = {pack:String})"
        )
        parameters: dict = {"pack": self.pack, "limit": PAGE_SIZE, "offset": (max(page, 1) - 1) * PAGE_SIZE}
        if decision:
            sql += " AND a.decision = {decision:String}"
            parameters["decision"] = decision
        sql += " ORDER BY a.ts DESC LIMIT {limit:UInt32} OFFSET {offset:UInt32}"
        return [
            AuditRow(ts=_aware(ts), trace_id=trace_id, user_id=user_id, role=role, decision=verdict, dataset=dataset,
                     blocked_tables=list(blocked), reason=reason)
            for ts, trace_id, user_id, role, verdict, dataset, blocked, reason in self.query(sql, parameters)
        ]

    def screening(self, *, verdict: str | None = None, source: str | None = None, page: int = 1) -> list[ScreeningRow]:
        where, parameters = [], {"limit": PAGE_SIZE, "offset": (max(page, 1) - 1) * PAGE_SIZE}
        if verdict:
            where.append("verdict = {verdict:String}")
            parameters["verdict"] = verdict
        if source:
            where.append("source = {source:String}")
            parameters["source"] = source
        sql = "SELECT ts, trace_id, user_id, source, verdict, mode, score, rule_hits FROM agent_logs.input_screening"
        sql += (" WHERE " + " AND ".join(where)) if where else ""
        sql += " ORDER BY ts DESC LIMIT {limit:UInt32} OFFSET {offset:UInt32}"
        return [
            ScreeningRow(ts=_aware(ts), trace_id=trace_id, user_id=user_id, source=src, verdict=result, mode=mode,
                         score=None if score is None else float(score), rule_hits=list(hits))
            for ts, trace_id, user_id, src, result, mode, score, hits in self.query(sql, parameters)
        ]

    def costs(self, *, start: date, end: date) -> list[CostRow]:
        rows = self.query(
            "SELECT toString(toDate(ts)) AS day, alias, provider, model, tier, count() AS calls, sum(cost_usd) AS cost "
            "FROM agent_logs.llm_calls WHERE ts >= {start:Date} AND ts < {end:Date} "
            "GROUP BY day, alias, provider, model, tier ORDER BY day, alias, provider, model, tier",
            {"start": start, "end": end},
        )
        return [
            # Rows written through the LiteLLM Proxy have no provider column value; their alias names it.
            CostRow(day=day, alias=alias, model=model, tier=tier, provider=provider or provider_of(alias), calls=int(calls),
                    cost_usd=round(float(cost or 0.0), 6))
            for day, alias, provider, model, tier, calls, cost in rows
        ]

    @staticmethod
    def _conversation(row: Sequence) -> AdminConversation:
        conversation_id, user_id, title, deleted, updated_at = row
        return AdminConversation(conversation_id=conversation_id, user_id=user_id, title=title, deleted=bool(deleted),
                                 updated_at=_aware(updated_at))

    def conversations(self, *, user: str | None = None) -> list[AdminConversation]:
        sql = "SELECT conversation_id, user_id, title, deleted, updated_at FROM agent_logs.conversations FINAL"
        parameters: dict = {"limit": 200}
        if user:
            sql += " WHERE user_id = {user:String}"
            parameters["user"] = user
        sql += " ORDER BY updated_at DESC LIMIT {limit:UInt32}"
        return [self._conversation(row) for row in self.query(sql, parameters)]

    def conversation(self, conversation_id: str) -> AdminConversationThread | None:
        rows = self.query(
            "SELECT conversation_id, user_id, title, deleted, updated_at FROM agent_logs.conversations FINAL "
            "WHERE conversation_id = {id:String} LIMIT 1",
            {"id": conversation_id},
        )
        if not rows:
            return None
        messages = [
            AdminMessage(ts=_aware(ts), role=role, content=content, trace_id=trace_id, turn=int(turn),
                         revision=int(revision))
            for ts, role, content, trace_id, turn, revision in self.query(
                "SELECT ts, role, content, trace_id, turn, revision FROM agent_logs.chat_messages "
                "WHERE conversation_id = {id:String} ORDER BY turn, revision, ts",
                {"id": conversation_id},
            )
        ]
        return AdminConversationThread(conversation=self._conversation(rows[0]), messages=messages)

