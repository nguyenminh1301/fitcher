"""ClickHouse access control compiled from policies.yaml: names, DDL plans, reconciliation and apply."""

import hashlib
from pathlib import Path

from conftest import SCHEMA_DIR
import pytest

from app.packs.loader import load_pack
from app.packs.policy_compiler import (
    PROFILE_LIMITS,
    Grant,
    ManagedObjects,
    Names,
    RowPolicy,
    agent_password,
    allowlists,
    apply_policies,
    desired_objects,
    plan_statements,
    read_managed,
)

GOLDEN = Path(__file__).parent / "fixtures" / "policies" / "minimal.sql"


def _hash(user: str) -> str:
    return hashlib.sha256(user.encode()).hexdigest()


@pytest.fixture
def pack(pack_dir, edit_pack):
    """The fixture pack with a row-filtered role and an aggregate-only role next to its plain viewer."""
    def add_roles(data):
        base = data["roles"][0]
        data["roles"].append({**base, "id": "blue_viewer", "datasets": [
            {**base["datasets"][0], "row_filter": "widget_name = 'Blue Widget'"},
        ]})
        data["roles"].append({**base, "id": "summary_reader", "datasets": [{
            "dataset": "widget_sales", "columns": ["sold_on", "widget_name"],
            "aggregate_only": {"metrics": ["widget_revenue"], "min_group_size": 5},
        }]})

    edit_pack("policies.yaml", add_roles)
    edit_pack("datasets.yaml", lambda data: data["datasets"][0]["allowed_roles"].extend(["blue_viewer", "summary_reader"]))
    return load_pack(pack_dir, schema_dir=SCHEMA_DIR)


def test_names_are_scoped_by_pack():
    names = Names("shop")

    assert names.role("analyst") == "fitcher_role__shop__analyst"
    assert names.user("analyst") == "fitcher_agent__shop__analyst"
    assert names.profile == "fitcher_agent__shop"
    assert names.row_policy("analyst") == "fitcher_row__shop__analyst"
    assert names.view("analyst", "orders") == "fitcher_agg__shop__analyst__orders"


def test_agent_password_is_derived_per_user_and_needs_a_secret():
    first = agent_password("secret", "fitcher_agent__shop__a")

    assert first == agent_password("secret", "fitcher_agent__shop__a")
    assert first != agent_password("secret", "fitcher_agent__shop__b")
    assert first != agent_password("other", "fitcher_agent__shop__a")
    with pytest.raises(ValueError, match="secret"):
        agent_password("", "fitcher_agent__shop__a")


def test_allowlists_name_tables_for_column_grants_and_views_for_aggregate_grants(pack):
    assert allowlists(pack) == {
        "viewer": {
            "widget_sales": ["sale_ref", "sold_on", "widget_name", "sale_amount"],
            "widget_refunds": ["refund_ref", "refunded_on", "sale_ref", "refund_total"],
        },
        "blue_viewer": {"widget_sales": ["sale_ref", "sold_on", "widget_name", "sale_amount"]},
        "summary_reader": {
            "fitcher_agg__minimal__summary_reader__widget_sales": ["sold_on", "widget_name", "widget_revenue", "row_count"],
        },
    }


def test_statements_for_an_empty_cluster_match_the_golden_file(pack):
    statements = plan_statements(pack, ManagedObjects(), _hash)

    assert "\n".join(statements) + "\n" == GOLDEN.read_text(encoding="utf-8")


def test_profile_limits_cannot_be_lifted_with_zero(pack):
    profile = plan_statements(pack, ManagedObjects(), _hash)[0]

    assert "readonly = 2 CONST" in profile
    for name, (default, maximum) in PROFILE_LIMITS.items():
        assert f"{name} = {default} MIN 1 MAX {maximum}" in profile


def test_reapplying_an_unchanged_policy_revokes_and_drops_nothing(pack):
    statements = plan_statements(pack, desired_objects(pack), _hash)

    assert not [s for s in statements if s.startswith(("REVOKE", "DROP", "GRANT SELECT"))]


def _shrunk(pack, role_id, change):
    roles = [role if role.id != role_id else change(role) for role in pack.policies.roles]
    return pack.model_copy(update={"policies": pack.policies.model_copy(update={"roles": [r for r in roles if r]})})


def _without_column(role, column):
    grants = [grant.model_copy(update={"columns": [c for c in grant.columns if c != column]}) for grant in role.datasets]
    return role.model_copy(update={"datasets": grants})


def test_removed_column_is_revoked(pack):
    smaller = _shrunk(pack, "viewer", lambda role: _without_column(role, "sale_amount"))

    statements = plan_statements(smaller, desired_objects(pack), _hash)

    assert "REVOKE SELECT(`sale_amount`) ON `marts`.`widget_sales` FROM `fitcher_role__minimal__viewer`" in statements


def test_removed_dataset_is_revoked_column_by_column(pack):
    smaller = _shrunk(pack, "viewer", lambda role: role.model_copy(update={"datasets": role.datasets[:1]}))

    statements = plan_statements(smaller, desired_objects(pack), _hash)

    assert (
        "REVOKE SELECT(`refund_ref`, `refund_total`, `refunded_on`, `sale_ref`) ON `marts`.`widget_refunds` "
        "FROM `fitcher_role__minimal__viewer`"
    ) in statements


def test_removed_role_drops_its_user_role_row_policy_and_nothing_else(pack):
    smaller = _shrunk(pack, "blue_viewer", lambda role: None)

    statements = plan_statements(smaller, desired_objects(pack), _hash)

    assert "DROP USER IF EXISTS `fitcher_agent__minimal__blue_viewer`" in statements
    assert "DROP ROLE IF EXISTS `fitcher_role__minimal__blue_viewer`" in statements
    assert "DROP ROW POLICY IF EXISTS `fitcher_row__minimal__blue_viewer` ON `marts`.`widget_sales`" in statements
    # A dropped role takes its grants with it, so none is revoked one by one.
    assert not [s for s in statements if s.startswith("REVOKE")]


def test_removed_aggregate_grant_drops_its_view_and_revokes_its_grant(pack):
    viewer = next(role for role in pack.policies.roles if role.id == "viewer")
    smaller = _shrunk(pack, "summary_reader", lambda role: role.model_copy(update={"datasets": viewer.datasets[1:]}))

    statements = plan_statements(smaller, desired_objects(pack), _hash)

    assert "DROP VIEW IF EXISTS `marts`.`fitcher_agg__minimal__summary_reader__widget_sales`" in statements
    assert (
        "REVOKE SELECT ON `marts`.`fitcher_agg__minimal__summary_reader__widget_sales` "
        "FROM `fitcher_role__minimal__summary_reader`"
    ) in statements


def test_removed_row_filter_drops_the_row_policy(pack):
    def unfiltered(role):
        return role.model_copy(update={"datasets": [g.model_copy(update={"row_filter": None}) for g in role.datasets]})

    statements = plan_statements(_shrunk(pack, "blue_viewer", unfiltered), desired_objects(pack), _hash)

    assert "DROP ROW POLICY IF EXISTS `fitcher_row__minimal__blue_viewer` ON `marts`.`widget_sales`" in statements


def test_grants_beyond_the_policy_are_revoked_even_when_not_select(pack):
    current = desired_objects(pack)
    current.grants.add(Grant("fitcher_role__minimal__viewer", None, None, "INSERT", "marts"))
    current.grants.add(Grant("fitcher_role__minimal__viewer", None, None, "SELECT", None))

    statements = plan_statements(pack, current, _hash)

    assert "REVOKE INSERT ON `marts`.* FROM `fitcher_role__minimal__viewer`" in statements
    assert "REVOKE SELECT ON *.* FROM `fitcher_role__minimal__viewer`" in statements


class FakeAccess:
    """Admin connection that answers the system-table reads and records every command."""

    def __init__(self, managed: ManagedObjects):
        self.managed = managed
        self.queries: list[str] = []
        self.commands: list[str] = []

    def query(self, sql, settings=None):
        self.queries.append(sql)
        if "system.roles" in sql:
            return [[name] for name in self.managed.roles]
        if "system.users" in sql:
            return [[name] for name in self.managed.users]
        if "system.grants" in sql:
            return [[g.role, g.access, g.database, g.table, g.column] for g in self.managed.grants]
        if "system.row_policies" in sql:
            return [[p.name, p.table] for p in self.managed.row_policies]
        if "system.tables" in sql:
            return [[view] for view in self.managed.views]
        raise AssertionError(sql)

    def command(self, sql):
        self.commands.append(sql)


def test_read_managed_finds_objects_by_the_pack_prefixes_only():
    access = FakeAccess(ManagedObjects(roles={"fitcher_role__minimal__viewer"}))

    found = read_managed(access, "minimal")

    assert found.roles == {"fitcher_role__minimal__viewer"}
    assert all("'fitcher_" in sql and "__minimal__" in sql for sql in access.queries)
    users = next(sql for sql in access.queries if "system.users" in sql)
    assert "storage = 'local_directory'" in users


def test_apply_runs_the_plan_and_sends_only_password_hashes(pack):
    access = FakeAccess(ManagedObjects(row_policies={RowPolicy("fitcher_row__minimal__gone", "widget_sales")}))

    statements = apply_policies(pack, access, "lab-secret")

    assert access.commands == statements
    password = agent_password("lab-secret", "fitcher_agent__minimal__viewer")
    assert not any(password in command for command in access.commands)
    assert any(hashlib.sha256(password.encode()).hexdigest() in command for command in access.commands)
    assert "DROP ROW POLICY IF EXISTS `fitcher_row__minimal__gone` ON `marts`.`widget_sales`" in statements
