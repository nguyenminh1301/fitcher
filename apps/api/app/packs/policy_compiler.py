"""Compile ``policies.yaml`` into ClickHouse access control (DECISIONS §9).

ClickHouse is the real permission layer. For every policy role the compiler
keeps a ClickHouse role holding column grants on ``marts`` tables and a row
policy per filtered table. An aggregate-only grant becomes a view that groups
the table by the granted columns, computes the listed metrics and hides
groups smaller than the policy's minimum; the role is granted the view, never
the table. Each role has one login user that the api connects as, and all of
a pack's users share one settings profile whose limits a query can lower but
never raise or set to 0, which means unlimited.

Every managed object carries a pack-scoped name prefix, so applying a policy
reconciles ClickHouse to it: objects of the pack that the policy no longer
contains are revoked or dropped, and nothing outside the prefixes is touched.

User passwords are never stored: each is derived from one secret with
HMAC-SHA256 over the user name, and ClickHouse receives only its SHA-256 hash.
"""

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
import hashlib
import hmac
import re
from typing import Protocol

import sqlglot
from sqlglot import exp

from app.data.forbidden_functions import forbidden_function
from app.packs.models import DatasetGrant, Pack, Role

MARTS_DATABASE = "marts"
# Column of an aggregate-only view holding the number of rows in each group.
ROW_COUNT_COLUMN = "row_count"
# Per-query limits of the shared profile as (default, maximum).
PROFILE_LIMITS = {
    "max_execution_time": (30, 120),
    "max_result_rows": (10_000, 100_000),
    "max_memory_usage": (2_000_000_000, 4_000_000_000),
}
_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


class AccessControl(Protocol):
    """Admin access to ClickHouse: reads for the current state, commands for the DDL."""

    def query(self, sql: str, settings: dict | None = None) -> Sequence[Sequence]: ...

    def command(self, sql: str) -> None: ...


def quote(identifier: str) -> str:
    if not _IDENTIFIER.fullmatch(identifier):
        raise ValueError(f"unsafe identifier {identifier!r}")
    return f"`{identifier}`"


def _literal(text: str) -> str:
    return "'" + text.replace("\\", "\\\\").replace("'", "\\'") + "'"


@dataclass(frozen=True)
class Names:
    """Names of the ClickHouse objects managed for one pack."""

    pack: str

    @property
    def role_prefix(self) -> str:
        return f"fitcher_role__{self.pack}__"

    @property
    def user_prefix(self) -> str:
        return f"fitcher_agent__{self.pack}__"

    @property
    def row_policy_prefix(self) -> str:
        return f"fitcher_row__{self.pack}__"

    @property
    def view_prefix(self) -> str:
        return f"fitcher_agg__{self.pack}__"

    @property
    def profile(self) -> str:
        return f"fitcher_agent__{self.pack}"

    def role(self, role: str) -> str:
        return self.role_prefix + role

    def user(self, role: str) -> str:
        return self.user_prefix + role

    def row_policy(self, role: str) -> str:
        return self.row_policy_prefix + role

    def view(self, role: str, dataset: str) -> str:
        return f"{self.view_prefix}{role}__{dataset}"


def agent_password(secret: str, user: str) -> str:
    """The password of a managed user, derived from ``secret``; the api derives the same one to connect."""
    if not secret:
        raise ValueError("the agent password secret must not be empty")
    return hmac.new(secret.encode(), user.encode(), hashlib.sha256).hexdigest()


def check_row_filter(text: str, columns: Iterable[str]) -> str | None:
    """Return why ``text`` is not a usable row filter over ``columns``, or None when it is."""
    try:
        node = sqlglot.parse_one(text, read="clickhouse", into=exp.Condition)
    except sqlglot.errors.ParseError:
        return "does not parse as one expression"
    if node.find(exp.Query, exp.Subquery):
        return "must not contain a subquery"
    if name := forbidden_function(node):
        return f"function {name}() is not allowed"
    if node.find(exp.AggFunc):
        return "must not use an aggregate function"
    if not isinstance(node.unnest(), (exp.Predicate, exp.Connector, exp.Not, exp.Boolean)):
        return "must be a boolean condition such as a comparison"
    known = set(columns)
    for column in node.find_all(exp.Column):
        if column.table or column.name not in known:
            return f"unknown column '{column.sql(dialect='clickhouse')}'"
    return None


def adds_up(sql_expr: str) -> bool:
    """Whether a metric is one sum or count, so the per-group values of an aggregate-only view sum to the total."""
    try:
        node = sqlglot.parse_one(sql_expr, read="clickhouse", into=exp.Condition).unnest()
    except sqlglot.errors.ParseError:
        return False
    if isinstance(node, (exp.Sum, exp.Count, exp.CountIf)):
        return True
    return isinstance(node, exp.CombinedAggFunc) and node.name.lower() in ("sumif", "countif")


def view_columns(grant: DatasetGrant) -> list[str]:
    """Columns of an aggregate-only grant's view: the grouped columns, one per metric and the row count."""
    assert grant.aggregate_only is not None
    return [*grant.columns, *grant.aggregate_only.metrics, ROW_COUNT_COLUMN]


def allowlists(pack: Pack) -> dict[str, dict[str, list[str]]]:
    """``{role: {marts table or view: [columns]}}``: what each role may read, for the SQL guard."""
    names = Names(pack.name)
    return {
        role.id: {
            grant.dataset if grant.aggregate_only is None else names.view(role.id, grant.dataset):
                list(grant.columns) if grant.aggregate_only is None else view_columns(grant)
            for grant in role.datasets
        }
        for role in pack.policies.roles
    }


@dataclass(frozen=True)
class Grant:
    """One privilege of a role as ``system.grants`` lists it; None widens to every column, table or database."""

    role: str
    table: str | None
    column: str | None = None
    access: str = "SELECT"
    database: str | None = MARTS_DATABASE

    def on(self) -> str:
        if self.database is None:
            return "*.*"
        if self.table is None:
            return f"{quote(self.database)}.*"
        return f"{quote(self.database)}.{quote(self.table)}"


@dataclass(frozen=True)
class RowPolicy:
    name: str
    table: str


@dataclass
class ManagedObjects:
    """A pack's managed ClickHouse objects: found in the cluster, or wanted by its policies."""

    roles: set[str] = field(default_factory=set)
    users: set[str] = field(default_factory=set)
    grants: set[Grant] = field(default_factory=set)
    row_policies: set[RowPolicy] = field(default_factory=set)
    views: set[str] = field(default_factory=set)


def desired_objects(pack: Pack) -> ManagedObjects:
    names = Names(pack.name)
    wanted = ManagedObjects()
    for role in pack.policies.roles:
        role_name = names.role(role.id)
        wanted.roles.add(role_name)
        wanted.users.add(names.user(role.id))
        for grant in role.datasets:
            if grant.aggregate_only is not None:
                view = names.view(role.id, grant.dataset)
                wanted.views.add(view)
                wanted.grants.add(Grant(role_name, view))
                continue
            wanted.grants.update(Grant(role_name, grant.dataset, column) for column in grant.columns)
            if grant.row_filter:
                wanted.row_policies.add(RowPolicy(names.row_policy(role.id), grant.dataset))
    return wanted


def _view_sql(pack: Pack, names: Names, role: Role, grant: DatasetGrant) -> str:
    assert grant.aggregate_only is not None
    expressions = {metric.id: metric.sql_expr for metric in pack.metrics.metrics}
    selected = [
        *(quote(column) for column in grant.columns),
        *(f"{expressions[metric]} AS {quote(metric)}" for metric in grant.aggregate_only.metrics),
        f"count() AS {quote(ROW_COUNT_COLUMN)}",
    ]
    where = f" WHERE ({grant.row_filter})" if grant.row_filter else ""
    return (
        f"CREATE OR REPLACE VIEW {quote(MARTS_DATABASE)}.{quote(names.view(role.id, grant.dataset))} "
        f"DEFINER = CURRENT_USER SQL SECURITY DEFINER AS SELECT {', '.join(selected)} "
        f"FROM {quote(MARTS_DATABASE)}.{quote(grant.dataset)}{where} "
        f"GROUP BY {', '.join(quote(column) for column in grant.columns)} "
        f"HAVING count() >= {int(grant.aggregate_only.min_group_size)}"
    )


def _grant_statements(verb: str, grants: Iterable[Grant], direction: str) -> list[str]:
    """One statement per role, privilege and table, with the table's columns listed together."""
    columns: dict[tuple[str, str, str, bool], list[str]] = {}
    for grant in grants:
        columns.setdefault((grant.role, grant.access, grant.on(), grant.column is None), []).append(grant.column)
    statements = []
    for (role, access, on, whole), names in sorted(columns.items()):
        privilege = access if whole else f"{access}({', '.join(quote(name) for name in sorted(names))})"
        statements.append(f"{verb} {privilege} ON {on} {direction} {quote(role)}")
    return statements


def plan_statements(pack: Pack, current: ManagedObjects, password_hash: Callable[[str], str]) -> list[str]:
    """DDL that brings ClickHouse from ``current`` to the pack's policies.

    Objects are created before grants that name them, and dropped last, so
    every intermediate state grants no more than the old or the new policy.
    """
    names = Names(pack.name)
    wanted = desired_objects(pack)
    limits = ", ".join(f"{name} = {default} MIN 1 MAX {maximum}" for name, (default, maximum) in PROFILE_LIMITS.items())
    statements = [f"CREATE SETTINGS PROFILE OR REPLACE {quote(names.profile)} SETTINGS readonly = 2 CONST, {limits}"]
    statements += [f"CREATE ROLE IF NOT EXISTS {quote(role)}" for role in sorted(wanted.roles)]
    for role in pack.policies.roles:
        statements += [_view_sql(pack, names, role, grant) for grant in role.datasets if grant.aggregate_only]
    # The grants of a role that is about to be dropped go with the role.
    statements += _grant_statements(
        "REVOKE", (grant for grant in current.grants - wanted.grants if grant.role in wanted.roles), "FROM"
    )
    statements += _grant_statements("GRANT", wanted.grants - current.grants, "TO")
    for role in pack.policies.roles:
        for grant in role.datasets:
            if grant.row_filter and grant.aggregate_only is None:
                statements.append(
                    f"CREATE ROW POLICY OR REPLACE {quote(names.row_policy(role.id))} "
                    f"ON {quote(MARTS_DATABASE)}.{quote(grant.dataset)} USING ({grant.row_filter}) "
                    f"TO {quote(names.role(role.id))}"
                )
    statements += [
        f"DROP ROW POLICY IF EXISTS {quote(policy.name)} ON {quote(MARTS_DATABASE)}.{quote(policy.table)}"
        for policy in sorted(current.row_policies - wanted.row_policies, key=lambda policy: (policy.name, policy.table))
    ]
    for role in pack.policies.roles:
        user, role_name = names.user(role.id), names.role(role.id)
        identified = f"IDENTIFIED WITH sha256_hash BY {_literal(password_hash(user))}"
        statements += [
            f"CREATE USER IF NOT EXISTS {quote(user)} {identified}",
            f"GRANT {quote(role_name)} TO {quote(user)}",
            f"ALTER USER {quote(user)} {identified} DEFAULT ROLE {quote(role_name)} "
            f"SETTINGS PROFILE {_literal(names.profile)}",
        ]
    statements += [f"DROP USER IF EXISTS {quote(user)}" for user in sorted(current.users - wanted.users)]
    statements += [
        f"DROP VIEW IF EXISTS {quote(MARTS_DATABASE)}.{quote(view)}" for view in sorted(current.views - wanted.views)
    ]
    statements += [f"DROP ROLE IF EXISTS {quote(role)}" for role in sorted(current.roles - wanted.roles)]
    return statements


def read_managed(admin: AccessControl, pack: str) -> ManagedObjects:
    """Find the pack's managed objects in ClickHouse by their name prefixes."""
    names = Names(pack)
    roles = admin.query(f"SELECT name FROM system.roles WHERE startsWith(name, {_literal(names.role_prefix)})")
    users = admin.query(
        f"SELECT name FROM system.users WHERE startsWith(name, {_literal(names.user_prefix)}) "
        "AND storage = 'local_directory'"
    )
    grants = admin.query(
        "SELECT role_name, access_type, database, table, column FROM system.grants "
        f"WHERE startsWith(role_name, {_literal(names.role_prefix)}) AND is_partial_revoke = 0"
    )
    policies = admin.query(
        f"SELECT short_name, table FROM system.row_policies WHERE database = {_literal(MARTS_DATABASE)} "
        f"AND startsWith(short_name, {_literal(names.row_policy_prefix)})"
    )
    views = admin.query(
        f"SELECT name FROM system.tables WHERE database = {_literal(MARTS_DATABASE)} "
        f"AND startsWith(name, {_literal(names.view_prefix)})"
    )
    return ManagedObjects(
        roles={row[0] for row in roles},
        users={row[0] for row in users},
        grants={Grant(role, table, column, access, database) for role, access, database, table, column in grants},
        row_policies={RowPolicy(name, table) for name, table in policies},
        views={row[0] for row in views},
    )


def apply_policies(pack: Pack, admin: AccessControl, secret: str) -> list[str]:
    """Reconcile ClickHouse to the pack's policies as the admin user; return the statements run."""

    def password_hash(user: str) -> str:
        return hashlib.sha256(agent_password(secret, user).encode()).hexdigest()

    statements = plan_statements(pack, read_managed(admin, pack.name), password_hash)
    for statement in statements:
        admin.command(statement)
    return statements
