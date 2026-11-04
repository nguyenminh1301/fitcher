"""GET/PUT /admin/models: tiers, eligible aliases and audited changes, over a fake store and catalog."""

from datetime import datetime, UTC
import json

from fastapi.testclient import TestClient
import httpx
import pytest

from agent_fixtures import compiled_fixture
from auth_fixtures import token, verifier

from app.api import runtime
from app.llm.client import LiteLLMClient, Prompt
from app.llm.eligibility import eligibility, ReportSummary
from app.llm.model_store import CatalogError
from app.llm.tiers import BUILT_IN_DEFAULTS, CACHE_SECONDS, TierMap, TierStoreError
from app.main import app

DAY = datetime(2026, 11, 4, tzinfo=UTC)
DEFAULTS = dict(BUILT_IN_DEFAULTS)


def report(report_id: str, hour: int, passed: bool = True, regressed: bool | None = False, **tiers) -> ReportSummary:
    mapping = {**DEFAULTS, **{tier.replace("_", "-"): alias for tier, alias in tiers.items()}}
    return ReportSummary(report_id=report_id, ts=DAY.replace(hour=hour), tiers=mapping, passed=passed, regressed=regressed)


# eligibility

def test_an_alias_without_a_report_for_the_tier_is_not_eligible():
    state = eligibility([report("r1", 1)], "sql-small", "anthropic-small")

    assert not state.eligible and state.reason == "no eval report ran sql-small with anthropic-small"


def test_the_latest_report_decides():
    reports = [report("old", 1, sql_small="anthropic-small"), report("new", 2, passed=False, sql_small="anthropic-small")]

    state = eligibility(reports, "sql-small", "anthropic-small")

    assert (state.eligible, state.report_id) == (False, "new")
    assert "below the threshold" in state.reason
    assert eligibility(reports[:1], "sql-small", "anthropic-small").eligible


@pytest.mark.parametrize(("regressed", "reason"), [
    (True, "regressed against the baseline"), (None, "not compared with the baseline"),
])
def test_a_regression_or_a_missing_baseline_comparison_is_not_eligible(regressed, reason):
    state = eligibility([report("r1", 1, regressed=regressed, sql_small="gemini-small")], "sql-small", "gemini-small")

    assert not state.eligible and reason in state.reason


# api

class FakeModelStore:
    def __init__(self, reports: list[ReportSummary] | None = None):
        self.rows: dict[str, str] = {}
        self.writes: list[tuple[str, str, str]] = []
        self.actions = []
        self.report_rows = list(reports or [])
        self.fail_action = False

    def read(self) -> dict[str, str]:
        return dict(self.rows)

    def write(self, tier, alias, changed_by, changed_at):
        self.rows[tier] = alias
        self.writes.append((tier, alias, changed_by))

    def reports(self, pack):
        return list(self.report_rows)

    def record_action(self, record):
        if self.fail_action:
            raise RuntimeError("clickhouse refused the insert")
        self.actions.append(record)


class FakeCatalog:
    def __init__(self, aliases: list[str] | None = None, error: str | None = None):
        self._aliases = aliases if aliases is not None else [
            "anthropic-small", "openai-embed", "openai-large", "openai-medium", "openai-small",
        ]
        self._error = error

    def aliases(self):
        if self._error:
            raise CatalogError(self._error)
        return list(self._aliases)


REPORTS = [
    report("baseline", 1),
    report("anthropic", 2, sql_small="anthropic-small"),
    report("regressed", 0, regressed=True, sql_gen="anthropic-small"),
]


def admin_headers(user: str = "lab.admin") -> dict:
    return {"Authorization": f"Bearer {token(preferred_username=user, realm_access={'roles': ['admin']})}"}


@pytest.fixture
def store():
    return FakeModelStore(REPORTS)


@pytest.fixture
def tiers(store):
    return TierMap(DEFAULTS, store)


@pytest.fixture
def catalog():
    return FakeCatalog()


@pytest.fixture
def client(store, tiers, catalog):
    app.dependency_overrides[runtime.get_verifier] = lambda: verifier()
    app.dependency_overrides[runtime.get_compiled] = lambda: compiled_fixture()
    app.dependency_overrides[runtime.get_model_store] = lambda: store
    app.dependency_overrides[runtime.get_tier_map] = lambda: tiers
    app.dependency_overrides[runtime.get_catalog] = lambda: catalog
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def by_tier(body: dict) -> dict:
    return {item["tier"]: item for item in body["tiers"]}


def test_only_an_admin_reaches_the_models_page(client):
    viewer = {"Authorization": f"Bearer {token()}"}

    assert client.get("/admin/models", headers=viewer).status_code == 403
    assert client.put("/admin/models/sql-small", json={"alias": "anthropic-small"}, headers=viewer).status_code == 403
    assert client.get("/admin/models").status_code == 401


def test_the_listing_shows_every_tier_with_its_alias_provider_and_eligibility(client):
    response = client.get("/admin/models", headers=admin_headers())

    assert response.status_code == 200
    body = response.json()
    tiers = by_tier(body)
    assert list(tiers) == ["fast", "sql-small", "sql-gen", "sql-gen-hard", "embed"]
    small = tiers["sql-small"]
    assert (small["alias"], small["provider"], small["default_alias"]) == ("openai-small", "openai", "openai-small")
    assert (small["eligible"], small["report_id"]) == (True, "baseline")
    options = {option["alias"]: option for option in small["options"]}
    assert "openai-embed" not in options
    assert options["anthropic-small"]["eligible"] and options["anthropic-small"]["report_id"] == "anthropic"
    assert not options["openai-medium"]["eligible"]
    assert not {option["alias"]: option for option in tiers["sql-gen"]["options"]}["anthropic-small"]["eligible"]
    embed = tiers["embed"]
    assert (embed["editable"], embed["options"]) == (False, [])
    assert "full reindex" in embed["reason"]


def test_an_eligible_alias_is_mapped_audited_and_used_at_once(client, store, tiers):
    sent: list[dict] = []

    def gateway(request: httpx.Request) -> httpx.Response:
        sent.append(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": "SELECT 1"}}]})

    llm = LiteLLMClient("http://litellm:4000", "sk", http=httpx.Client(transport=httpx.MockTransport(gateway)), tiers=tiers)
    llm.text("sql-small", Prompt(system="s", user="u"))

    response = client.put("/admin/models/sql-small", json={"alias": "anthropic-small"}, headers=admin_headers())

    assert response.status_code == 200
    assert (response.json()["alias"], response.json()["provider"]) == ("anthropic-small", "anthropic")
    assert store.writes == [("sql-small", "anthropic-small", "lab.admin")]
    [action] = store.actions
    assert (action.actor, action.action, action.target, action.old_value, action.new_value) == (
        "lab.admin", "model_tier", "sql-small", "openai-small", "anthropic-small",
    )
    llm.text("sql-small", Prompt(system="s", user="u"))
    assert [body["model"] for body in sent] == ["openai-small", "anthropic-small"]


def test_another_process_reads_the_change_within_the_cache_window(client, store):
    now = [0.0]
    other = TierMap(DEFAULTS, store, clock=lambda: now[0])
    assert other.alias("sql-small") == "openai-small"

    client.put("/admin/models/sql-small", json={"alias": "anthropic-small"}, headers=admin_headers())

    now[0] = CACHE_SECONDS
    assert other.alias("sql-small") == "anthropic-small"


def test_an_ineligible_alias_is_refused_with_its_reason(client, store):
    response = client.put("/admin/models/sql-gen", json={"alias": "anthropic-small"}, headers=admin_headers())

    assert response.status_code == 409
    assert "regressed against the baseline" in response.json()["detail"]
    assert store.writes == [] and store.actions == []


@pytest.mark.parametrize(("tier", "alias", "code"), [
    ("embed", "openai-embed", 400),
    ("summarize", "openai-small", 404),
    ("sql-small", "gemini-small", 422),
])
def test_embed_an_unknown_tier_and_an_unloaded_alias_are_refused(client, store, tier, alias, code):
    assert client.put(f"/admin/models/{tier}", json={"alias": alias}, headers=admin_headers()).status_code == code
    assert store.writes == []


def test_an_unaudited_change_is_written_back(client, store, tiers):
    store.fail_action = True

    response = client.put("/admin/models/sql-small", json={"alias": "anthropic-small"}, headers=admin_headers())

    assert response.status_code == 503
    assert store.writes[-1][:2] == ("sql-small", "openai-small")
    assert tiers.alias("sql-small") == "openai-small"


def test_without_the_catalog_the_listing_has_no_options_and_changes_are_refused():
    app.dependency_overrides[runtime.get_verifier] = lambda: verifier()
    app.dependency_overrides[runtime.get_compiled] = lambda: compiled_fixture()
    store = FakeModelStore(REPORTS)
    app.dependency_overrides[runtime.get_model_store] = lambda: store
    app.dependency_overrides[runtime.get_tier_map] = lambda: TierMap(DEFAULTS, store)
    app.dependency_overrides[runtime.get_catalog] = lambda: FakeCatalog(error="gateway down")
    try:
        with TestClient(app) as client:
            body = client.get("/admin/models", headers=admin_headers()).json()
            assert body["catalog_error"] == "gateway down"
            assert all(item["options"] == [] for item in body["tiers"])
            change = client.put("/admin/models/sql-small", json={"alias": "anthropic-small"}, headers=admin_headers())
            assert change.status_code == 503
    finally:
        app.dependency_overrides.clear()


def test_an_unreadable_mapping_keeps_the_defaults():
    class Broken(FakeModelStore):
        def read(self):
            raise TierStoreError("down")

    assert TierMap(DEFAULTS, Broken()).alias("sql-gen") == "openai-medium"
