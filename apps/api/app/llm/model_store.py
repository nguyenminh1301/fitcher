"""The ClickHouse side of model routing, as the ``model_tiers_admin`` user (DECISIONS §2, §15).

It reads and writes the tier mapping in ``data_meta.model_tiers``, reads the
eval reports of a pack that make an alias eligible for a tier, and records
each change an admin makes in ``agent_logs.admin_actions``. ``CatalogClient``
lists the aliases the LiteLLM gateway loaded, which are the aliases whose
provider key is set.
"""

from collections.abc import Mapping
from datetime import datetime, timedelta
import os
import threading

import clickhouse_connect
import httpx

from app.llm.eligibility import ReportSummary
from app.llm.tiers import TierStoreError
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


class CatalogError(RuntimeError):
    """The gateway did not list its aliases."""


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
    )


class ClickHouseModelStore:
    """Implements ``TierStore`` and reads the eval reports and writes the audit rows of the Models page."""

    def __init__(self, client):
        self._client = client
        self._last_change: datetime | None = None
        self._lock = threading.Lock()

    def read(self) -> dict[str, str]:
        try:
            rows = self._client.query(
                "SELECT tier, argMax(alias, changed_at) FROM data_meta.model_tiers GROUP BY tier"
            ).result_rows
        except Exception as error:  # noqa: BLE001 - any ClickHouse failure keeps the previous mapping
            raise TierStoreError(f"cannot read data_meta.model_tiers: {type(error).__name__}") from error
        return {str(tier): str(alias) for tier, alias in rows}

    def write(self, tier: str, alias: str, changed_by: str, changed_at: datetime) -> None:
        """Insert a mapping row; each row's ``changed_at`` is after the previous one, so the latest always wins."""
        with self._lock:
            if self._last_change is not None and changed_at <= self._last_change:
                changed_at = self._last_change + timedelta(milliseconds=1)
            self._client.insert(
                "data_meta.model_tiers", [[tier, alias, changed_by, changed_at]],
                column_names=["tier", "alias", "changed_by", "changed_at"],
            )
            self._last_change = changed_at

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


class CatalogClient:
    """``GET /v1/models`` of the LiteLLM gateway: the aliases it loaded."""

    def __init__(self, base_url: str, api_key: str, http: httpx.Client | None = None):
        self._url = f"{base_url.rstrip('/')}/v1/models"
        self._headers = {"Authorization": f"Bearer {api_key}"}
        self._http = http or httpx.Client(timeout=TIMEOUT_SECONDS)

    def aliases(self) -> list[str]:
        try:
            response = self._http.get(self._url, headers=self._headers)
        except httpx.HTTPError as error:
            raise CatalogError(f"the gateway did not list its models: {type(error).__name__}") from error
        if response.status_code != 200:
            raise CatalogError(f"the gateway returned HTTP {response.status_code} for its models")
        try:
            data = response.json().get("data", [])
            return sorted({str(item["id"]) for item in data})
        except (ValueError, AttributeError, KeyError, TypeError) as error:
            raise CatalogError("the gateway listed its models in an unknown shape") from error
