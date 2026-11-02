"""Every pack role against every dataset, straight on ClickHouse with the SQL guard bypassed.

Runs only with ``POLICY_LIVE_TEST=1``, ``ACTIVE_PACK`` compiled (its users
exist), ``CLICKHOUSE_AGENT_PASSWORD`` and the admin credentials. Each role
connects as its own user and runs raw SQL: a granted dataset reads its granted
columns and is refused the others, a dataset the role lacks is refused, an
aggregate-only dataset is refused while its view hides small groups, and a
row-filtered dataset returns exactly the rows its filter selects. Nothing here
names a pack's tables or columns; they come from the pack. Run with ``-s`` to
print the matrix.
"""

import os
from pathlib import Path

import pytest

from app.data.clickhouse import agent_client
from app.packs.compiler import approved_pack
from app.packs.loader import load_pack
from app.packs.policy_compiler import Names

pytestmark = pytest.mark.skipif(os.environ.get("POLICY_LIVE_TEST") != "1", reason="needs a running ClickHouse")
ROOT = Path(__file__).resolve().parents[3]


def _env() -> dict:
    return {**os.environ, "CLICKHOUSE_HOST": os.environ.get("CLICKHOUSE_HOST", "localhost")}


def _denied(client, sql: str) -> bool:
    try:
        client.query(sql)
    except Exception as error:  # noqa: BLE001 - the error text names the refusal
        if "ACCESS_DENIED" in str(error) or "497" in str(error):
            return True
        raise
    return False


def test_every_role_reads_exactly_what_its_policy_grants():
    clickhouse_connect = pytest.importorskip("clickhouse_connect")
    packs_dir = Path(os.environ.get("PACKS_DIR", ROOT / "packs"))
    pack = approved_pack(load_pack(packs_dir / os.environ["ACTIVE_PACK"]))
    admin = clickhouse_connect.get_client(
        host=_env()["CLICKHOUSE_HOST"], username=os.environ["CLICKHOUSE_ADMIN_USER"],
        password=os.environ["CLICKHOUSE_ADMIN_PASSWORD"],
    )
    names = Names(pack.name)
    columns = {dataset.id: [column.name for column in dataset.columns] for dataset in pack.datasets.datasets}
    rows, failures = [], []

    for role in pack.policies.roles:
        client = agent_client(pack.name, role.id, _env())
        grants = {grant.dataset: grant for grant in role.datasets}
        for dataset, all_columns in columns.items():
            grant = grants.get(dataset)
            table = f"marts.`{dataset}`"
            if grant is None:
                outcome = "deny" if _denied(client, f"SELECT count() FROM {table}") else "READ (expected deny)"
            elif grant.aggregate_only is not None:
                view = f"marts.`{names.view(role.id, dataset)}`"
                smallest = client.query(f"SELECT min(row_count) FROM {view}").result_rows[0][0]
                table_denied = _denied(client, f"SELECT count() FROM {table}")
                ok = table_denied and (smallest is None or smallest >= grant.aggregate_only.min_group_size)
                outcome = f"aggregate-only (min group {smallest})" if ok else f"aggregate-only BROKEN ({smallest}, table denied={table_denied})"
            else:
                client.query(f"SELECT `{grant.columns[0]}` FROM {table} LIMIT 1")
                hidden = [column for column in all_columns if column not in grant.columns]
                column_denied = not hidden or _denied(client, f"SELECT `{hidden[0]}` FROM {table} LIMIT 1")
                outcome = f"{len(grant.columns)} columns" if column_denied else "UNGRANTED COLUMN READ"
                if grant.row_filter:
                    seen = client.query(f"SELECT count() FROM {table}").result_rows[0][0]
                    expected = admin.query(f"SELECT count() FROM {table} WHERE {grant.row_filter}").result_rows[0][0]
                    outcome += f", filtered rows {seen}" if seen == expected else f", FILTER BROKEN ({seen} != {expected})"
            rows.append(f"{role.id:<20} {dataset:<20} {outcome}")
            if any(word in outcome for word in ("expected", "BROKEN", "UNGRANTED")):
                failures.append(rows[-1])

    print("\n" + "\n".join(rows))
    assert failures == []
