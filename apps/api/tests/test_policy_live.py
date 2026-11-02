"""Applying and shrinking a pack's policies on a running ClickHouse.

Runs only with ``POLICY_LIVE_TEST=1``, the admin credentials in
``CLICKHOUSE_ADMIN_USER`` / ``CLICKHOUSE_ADMIN_PASSWORD`` and the pack in
``ACTIVE_PACK`` (``PACKS_DIR`` defaults to the repository's ``packs``). The
pack's policies are applied under the separate pack name ``liveprobe``, so the
real pack's objects are never touched, and every managed object of that name
is dropped again at the end. Nothing here names a pack's tables or columns:
the roles, datasets and columns come from the pack itself.
"""

import os
from pathlib import Path

import pytest

from app.packs.compiler import approved_pack
from app.packs.loader import load_pack
from app.packs.policy_compiler import Names, agent_password, apply_policies, read_managed

pytestmark = pytest.mark.skipif(os.environ.get("POLICY_LIVE_TEST") != "1", reason="needs a running ClickHouse")

PROBE = "liveprobe"
SECRET = "liveprobe-secret"
ROOT = Path(__file__).resolve().parents[3]


class Admin:
    def __init__(self, client):
        self.client = client

    def query(self, sql, settings=None):
        return self.client.query(sql, settings=settings).result_rows

    def command(self, sql):
        self.client.command(sql)


def _client(user: str, password: str):
    clickhouse_connect = pytest.importorskip("clickhouse_connect")
    return clickhouse_connect.get_client(
        host=os.environ.get("CLICKHOUSE_HOST", "localhost"),
        port=int(os.environ.get("CLICKHOUSE_HTTP_PORT", "8123")),
        username=user, password=password, autogenerate_session_id=False,
    )


def _as_role(role: str):
    user = Names(PROBE).user(role)
    return _client(user, agent_password(SECRET, user))


def _with_roles(pack, roles):
    return pack.model_copy(update={"policies": pack.policies.model_copy(update={"roles": roles})})


@pytest.fixture
def admin():
    return Admin(_client(os.environ["CLICKHOUSE_ADMIN_USER"], os.environ["CLICKHOUSE_ADMIN_PASSWORD"]))


@pytest.fixture
def pack(admin):
    packs_dir = Path(os.environ.get("PACKS_DIR", ROOT / "packs"))
    loaded = approved_pack(load_pack(packs_dir / os.environ["ACTIVE_PACK"])).model_copy(update={"name": PROBE})
    yield loaded
    apply_policies(_with_roles(loaded, []), admin, SECRET)


def _table_role(pack):
    """A role with a plain grant of at least two columns, and that grant."""
    for role in pack.policies.roles:
        for grant in role.datasets:
            if grant.aggregate_only is None and len(grant.columns) >= 2:
                return role, grant
    pytest.skip("the pack has no role with a column grant of two or more columns")


def test_policy_grants_exactly_its_columns(pack, admin):
    apply_policies(pack, admin, SECRET)
    role, grant = _table_role(pack)
    client = _as_role(role.id)

    client.query(f"SELECT `{grant.columns[0]}` FROM marts.`{grant.dataset}` LIMIT 1")
    other = sorted(
        {column.name for dataset in pack.datasets.datasets if dataset.id == grant.dataset for column in dataset.columns}
        - set(grant.columns)
    )
    if other:
        with pytest.raises(Exception, match="ACCESS_DENIED"):
            client.query(f"SELECT `{other[0]}` FROM marts.`{grant.dataset}` LIMIT 1")


def test_limits_cannot_be_lifted_with_zero(pack, admin):
    apply_policies(pack, admin, SECRET)
    role, grant = _table_role(pack)

    with pytest.raises(Exception, match="SETTING_CONSTRAINT_VIOLATION"):
        _as_role(role.id).query("SELECT 1", settings={"max_execution_time": 0})


def test_shrinking_the_policy_revokes_and_drops_on_the_cluster(pack, admin):
    apply_policies(pack, admin, SECRET)
    role, grant = _table_role(pack)
    dropped_column = grant.columns[-1]
    smaller_grant = grant.model_copy(update={"columns": grant.columns[:-1]})
    smaller_role = role.model_copy(update={"datasets": [smaller_grant if g is grant else g for g in role.datasets]})
    others = [r for r in pack.policies.roles if r.id != role.id]

    apply_policies(_with_roles(pack, [smaller_role, *others]), admin, SECRET)
    with pytest.raises(Exception, match="ACCESS_DENIED"):
        _as_role(role.id).query(f"SELECT `{dropped_column}` FROM marts.`{grant.dataset}` LIMIT 1")

    apply_policies(_with_roles(pack, [r for r in pack.policies.roles if r.id != role.id]), admin, SECRET)
    found = read_managed(admin, PROBE)
    assert Names(PROBE).role(role.id) not in found.roles
    assert Names(PROBE).user(role.id) not in found.users
    with pytest.raises(Exception, match="AUTHENTICATION_FAILED|Authentication failed|516"):
        _as_role(role.id).query("SELECT 1")


def test_aggregate_only_role_reads_its_view_but_not_the_table(pack, admin):
    apply_policies(pack, admin, SECRET)
    aggregate = [(role, grant) for role in pack.policies.roles for grant in role.datasets if grant.aggregate_only]
    if not aggregate:
        pytest.skip("the pack has no aggregate-only grant")
    role, grant = aggregate[0]
    client = _as_role(role.id)
    view = Names(PROBE).view(role.id, grant.dataset)

    smallest = client.query(f"SELECT min(row_count) FROM marts.`{view}`").result_rows[0][0]
    assert smallest >= grant.aggregate_only.min_group_size
    with pytest.raises(Exception, match="ACCESS_DENIED"):
        client.query(f"SELECT count() FROM marts.`{grant.dataset}`")


def test_row_filtered_role_sees_only_matching_rows(pack, admin):
    apply_policies(pack, admin, SECRET)
    filtered = [
        (role, grant) for role in pack.policies.roles for grant in role.datasets
        if grant.row_filter and grant.aggregate_only is None
    ]
    if not filtered:
        pytest.skip("the pack has no row-filtered grant")
    role, grant = filtered[0]

    seen = _as_role(role.id).query(f"SELECT count() FROM marts.`{grant.dataset}`").result_rows[0][0]
    expected = admin.query(f"SELECT count() FROM marts.`{grant.dataset}` WHERE {grant.row_filter}")[0][0]
    total = admin.query(f"SELECT count() FROM marts.`{grant.dataset}`")[0][0]
    assert seen == expected < total
