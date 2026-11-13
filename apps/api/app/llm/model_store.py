"""The ClickHouse side of the Models page, as the ``model_tiers_admin`` user (DECISIONS §2, §15).

It reads the eval reports of a pack that the Models page shows next to each
tier's model, and records each change an admin makes in
``agent_logs.admin_actions``. The tier mapping itself lives in the app state;
``read`` returns the mapping the LiteLLM Proxy era kept in
``data_meta.model_tiers``, which bootstrap copies once.
"""

from collections.abc import Mapping
import os

import clickhouse_connect

from app.llm.eligibility import ReportSummary
from app.observability.events import AdminActionRecord

USER = "model_tiers_admin"
PASSWORD_SETTING = "CLICKHOUSE_MODEL_TIERS_PASSWORD"
TIMEOUT_SECONDS = 10
# The latest eval report of every tier and alias of a pack: the only report eligibility reads.
LATEST_REPORTS = (
    "SELECT tier, alias, argMax(report_id, ts), max(ts), argMax(passed, ts), argMax(regressed, ts)"
    " FROM agent_logs.eval_reports ARRAY JOIN mapKeys(tiers) AS tier, mapValues(tiers) AS alias"
    " WHERE pack = {pack:String} GROUP BY tier, alias"
)


def model_tiers_client(env: Mapping[str, str] | None = None):
    env = os.environ if env is None else env
    password = env.get(PASSWORD_SETTING, "")
    if not password:
        raise RuntimeError(f"{PASSWORD_SETTING} must be set")
    return clickhouse_connect.get_client(
        host=env.get("CLICKHOUSE_HOST", "clickhouse"),
        port=int(env.get("CLICKHOUSE_HTTP_PORT", "8123")),
        username=USER,
        password=password,
        connect_timeout=TIMEOUT_SECONDS,
        send_receive_timeout=TIMEOUT_SECONDS,
        # Shared across concurrent requests: a session would serialize them and refuse overlaps.
        autogenerate_session_id=False,
    )


class ClickHouseModelStore:
    """Reads the eval reports and the old tier mapping, and writes the audit rows of the Models page."""

    def __init__(self, client):
        self._client = client

    def read(self) -> dict[str, str]:
        try:
            rows = self._client.query(
                "SELECT tier, argMax(alias, changed_at) FROM data_meta.model_tiers GROUP BY tier"
            ).result_rows
        except Exception as error:  # noqa: BLE001 - any ClickHouse failure keeps the previous mapping
            raise RuntimeError(f"cannot read data_meta.model_tiers: {type(error).__name__}") from error
        return {str(tier): str(alias) for tier, alias in rows}

    def reports(self, pack: str) -> list[ReportSummary]:
        """The latest eval report of the pack for every tier and alias, one summary per pair."""
        rows = self._client.query(LATEST_REPORTS, parameters={"pack": pack}).result_rows
        return [
            ReportSummary(report_id=report_id, ts=ts, tiers={tier: alias}, passed=bool(passed), regressed=regressed)
            for tier, alias, report_id, ts, passed, regressed in rows
        ]

    def record_action(self, record: AdminActionRecord) -> None:
        self._client.insert(
            f"agent_logs.{record.TABLE}", [list(record.model_dump().values())], column_names=list(type(record).model_fields),
        )
