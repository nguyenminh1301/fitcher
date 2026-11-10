"""Propose examples for review from disliked or failed data questions (DECISIONS §11 step 8).

Run with ``docker compose run --rm jobs python -m jobs.propose_examples --pack <name> [--days 90]``.
Every eligible run of the pack in the last ``--days`` days becomes one
redacted row of ``agent_logs.example_proposals``; a reviewer approves or
deletes it in the console's Review section. No LLM is called.
"""

import argparse
from datetime import UTC, datetime, timedelta
import sys

from clickhouse_connect.driver.exceptions import Error as ClickHouseError

from app.feedback.proposals import propose
from app.feedback.store import ClickHouseProposalStore
from jobs.lib.clickhouse import admin_client

DEFAULT_DAYS = 90


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--pack", required=True)
    parser.add_argument("--days", type=int, default=DEFAULT_DAYS, help="look back this many days")
    args = parser.parse_args(argv)
    try:
        client = admin_client()
        summary = propose(ClickHouseProposalStore(client, client), args.pack,
                          since=datetime.now(UTC) - timedelta(days=args.days))
    except (ClickHouseError, RuntimeError) as error:
        print(error, file=sys.stderr)
        return 1
    print(f"Pack {args.pack}: {len(summary.added)} proposals added, {len(summary.skipped)} runs skipped")
    for trace_id in summary.added:
        print(f"  proposed from {trace_id}")
    reasons: dict[str, int] = {}
    for reason in summary.skipped.values():
        reasons[reason] = reasons.get(reason, 0) + 1
    for reason, count in sorted(reasons.items()):
        print(f"  skipped {count}: {reason}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
