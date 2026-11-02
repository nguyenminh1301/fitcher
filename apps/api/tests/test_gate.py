"""The gate: a QuerySpec the asking role may not read is denied before any SQL, with an audit row."""

from dataclasses import replace

from agent_fixtures import deps, extraction_reply
from fakes import FakeLogWriter
import pytest

from app.agent.nodes.build_spec import make_spec
from app.agent.nodes.gate import authorize, gate
from app.packs.models import AggregateOnly
from test_agent_nodes import state_for


def _pack_with(*roles):
    agent = deps([])
    pack = agent.compiled.pack
    policies = pack.policies.model_copy(update={"roles": [*pack.policies.roles, *roles]})
    return pack.model_copy(update={"policies": policies})


def _role(role_id, datasets):
    base = deps([]).compiled.pack.policies.roles[0]
    return base.model_copy(update={"id": role_id, "datasets": datasets})


def _grant(index, **updates):
    return deps([]).compiled.pack.policies.roles[0].datasets[index].model_copy(update=updates)


def _spec(**extraction):
    state = state_for(extraction_reply(**extraction))
    return make_spec(state, deps([]).compiled)


def test_role_with_the_dataset_and_its_columns_is_allowed():
    assert authorize(_spec(), deps([]).compiled.pack, "viewer", "en") is None


def test_role_without_the_dataset_is_denied_naming_it():
    pack = _pack_with(_role("refunds_clerk", [_grant(1)]))

    denial = authorize(_spec(), pack, "refunds_clerk", "en")

    assert denial.dataset == "widget_sales"
    assert denial.blocked == ["widget_sales"]
    assert "refunds_clerk" in denial.message and "widget_sales" in denial.message
    assert "nothing was queried" in denial.message


def test_column_the_spec_groups_by_must_be_granted():
    pack = _pack_with(_role("no_names", [_grant(0, columns=["sale_ref", "sold_on", "sale_amount"])]))

    denial = authorize(_spec(), pack, "no_names", "en")

    assert denial.blocked == ["widget_sales.widget_name"]


def test_column_a_metric_reads_must_be_granted():
    pack = _pack_with(_role("no_amounts", [_grant(0, columns=["sale_ref", "sold_on", "widget_name"])]))

    denial = authorize(_spec(), pack, "no_amounts", "en")

    assert denial.blocked == ["widget_sales.sale_amount"]


def _summary_reader(columns=("sold_on", "widget_name"), metrics=("widget_revenue",)):
    grant = _grant(0, columns=list(columns), aggregate_only=AggregateOnly(metrics=list(metrics), min_group_size=5))
    return _pack_with(_role("summary_reader", [grant]))


def test_aggregate_only_role_is_allowed_its_grouped_columns_and_metrics():
    assert authorize(_spec(), _summary_reader(), "summary_reader", "en") is None


def test_aggregate_only_role_is_denied_a_column_outside_its_groups():
    denial = authorize(_spec(), _summary_reader(columns=("sold_on",)), "summary_reader", "en")

    assert denial.blocked == ["widget_sales.widget_name"]
    assert "only totals" in denial.message


def test_aggregate_only_role_needs_the_time_column_for_periods():
    denial = authorize(_spec(), _summary_reader(columns=("widget_name",)), "summary_reader", "en")

    assert denial.blocked == ["widget_sales.sold_on"]


def test_denial_is_written_in_the_language_of_the_question():
    pack = _pack_with(_role("refunds_clerk", [_grant(1)]))

    denial = authorize(_spec(), pack, "refunds_clerk", "vi")

    assert "không được đọc" in denial.message and "chưa có truy vấn nào" in denial.message


def test_gate_node_denies_and_writes_a_deny_audit_row():
    logs = FakeLogWriter()
    agent = replace(deps([]), compiled=deps([]).compiled.model_copy(update={
        "pack": _pack_with(_role("refunds_clerk", [_grant(1)])),
    }), role="refunds_clerk", logs=logs, user_id="u1")
    state = {**state_for(extraction_reply()), "trace_id": "t1"}
    state["spec"] = make_spec(state, agent.compiled)

    update = gate(state, agent)

    assert update["denial"].blocked == ["widget_sales"]
    [audit] = [record for record in logs.queued if record.TABLE == "audit"]
    assert (audit.trace_id, audit.user_id, audit.role, audit.decision) == ("t1", "u1", "refunds_clerk", "DENY")
    assert (audit.dataset, audit.blocked_tables) == ("widget_sales", ["widget_sales"])


def test_gate_node_lets_a_permitted_spec_through_without_an_audit_row():
    logs = FakeLogWriter()
    agent = replace(deps([]), logs=logs)
    state = {**state_for(extraction_reply()), "trace_id": "t1"}
    state["spec"] = make_spec(state, agent.compiled)

    assert gate(state, agent) == {}
    assert logs.queued == []


@pytest.mark.parametrize("language", ["fr", "ja"])
def test_other_languages_get_the_english_denial(language):
    pack = _pack_with(_role("refunds_clerk", [_grant(1)]))

    assert "nothing was queried" in authorize(_spec(), pack, "refunds_clerk", language).message
