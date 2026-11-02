"""Deny a question the asking role may not read, before any SQL (DECISIONS §6 step 8).

The gate compares the QuerySpec with the role's grants in ``policies.yaml``:
the dataset must be granted, and so must every column the query needs, which
are the grouped and filtered columns, the time column when periods are named
and, for a plain grant, the columns the metric expressions read. An
aggregate-only role may use only its grouping columns and listed metrics.
A denial ends the run with a message in the question's language, says that
nothing was queried, and writes a DENY row to ``agent_logs.audit``; it never
enters the SQL retry loop. ClickHouse remains the real permission layer.
"""

import sqlglot
from sqlglot import exp
from pydantic import BaseModel, ConfigDict

from app.agent.audit import audit
from app.agent.state import AgentDeps, AgentState
from app.contracts.query_spec import QuerySpec
from app.packs.models import Pack


class Denial(BaseModel):
    model_config = ConfigDict(frozen=True)

    dataset: str
    # The dataset, or ``dataset.column`` / ``dataset.metric`` items, the role may not read.
    blocked: list[str]
    message: str


def _metric_columns(sql_expr: str) -> list[str]:
    return [column.name for column in sqlglot.parse_one(sql_expr, read="clickhouse").find_all(exp.Column)]


def _message(role: str, blocked: list[str], language: str, aggregate: str | None) -> str:
    whole_dataset = len(blocked) == 1 and "." not in blocked[0]
    if language == "vi":
        what = f"bộ dữ liệu {blocked[0]}" if whole_dataset else f"{', '.join(blocked)}"
        scope = f"chỉ xem được {aggregate}, còn câu hỏi này cần {what}" if aggregate else f"không được đọc {what}"
        return f"Vai trò {role} {scope}, nên chưa có truy vấn nào được chạy. Hãy hỏi quản trị viên nếu bạn cần quyền truy cập."
    what = f"the dataset {blocked[0]}" if whole_dataset else ", ".join(blocked)
    scope = f"sees only {aggregate}, and this question needs {what}" if aggregate else f"cannot read {what}"
    return f"Your role {role} {scope}, so nothing was queried. Ask an administrator if you need access."


def authorize(spec: QuerySpec, pack: Pack, role: str, language: str) -> Denial | None:
    """None when ``role`` may answer ``spec``, else the denial naming what it may not read."""
    grants = {grant.dataset: grant for item in pack.policies.roles if item.id == role for grant in item.datasets}
    grant = grants.get(spec.dataset)
    if grant is None:
        blocked = [spec.dataset]
        return Denial(dataset=spec.dataset, blocked=blocked, message=_message(role, blocked, language, None))
    dataset = next(item for item in pack.datasets.datasets if item.id == spec.dataset)
    needed = [*spec.dimensions, *(item.column for item in spec.filters)]
    if spec.periods:
        needed.append(dataset.time_column)
    metrics = {metric.id: metric for metric in pack.metrics.metrics}
    aggregate = None
    blocked_metrics: list[str] = []
    if grant.aggregate_only is None:
        for metric_id in spec.metric_ids:
            needed += _metric_columns(metrics[metric_id].sql_expr)
    else:
        blocked_metrics = [f"{spec.dataset}.{m}" for m in spec.metric_ids if m not in grant.aggregate_only.metrics]
        names = ", ".join(metrics[m].name for m in grant.aggregate_only.metrics)
        aggregate = (
            f"tổng {names} theo {', '.join(grant.columns)} trong {spec.dataset}" if language == "vi"
            else f"totals of {names} by {', '.join(grant.columns)} in {spec.dataset}"
        )
    blocked = [*dict.fromkeys(f"{spec.dataset}.{c}" for c in needed if c not in grant.columns), *blocked_metrics]
    if not blocked:
        return None
    return Denial(dataset=spec.dataset, blocked=blocked, message=_message(role, blocked, language, aggregate))


def gate(state: AgentState, deps: AgentDeps) -> dict:
    language = getattr(state.get("extraction"), "language", "en")
    denial = authorize(state["spec"], deps.compiled.pack, deps.role, language)
    if denial is None:
        return {}
    audit(state, deps, "DENY", denial.dataset, denial.blocked, f"gate: role {deps.role} may not read {', '.join(denial.blocked)}")
    return {"denial": denial}
