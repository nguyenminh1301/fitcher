"""Ask one data question from the command line and print the SQL, result and summary.

Run with ``docker compose run --rm api python -m jobs.ask "<question>"``. Each
run sends billable requests to the LiteLLM aliases. This entry point answers
``data_query`` questions only: without the router and clarify branch it exits
with code 2 and the reason when a question names no measure or period, or its
measure is ambiguous. A run whose SQL could not be repaired, or that broke a
policy, exits with code 1 and prints the last SQL and error.

``--inject-sql-fault`` corrupts the first generated query with a call to an
unknown function, so a live run shows the repair loop at work.
"""

import argparse
from datetime import date
from pathlib import Path
import re
import sys

import sqlglot
from sqlglot.tokens import TokenType

from app.agent.graph import run_question
from app.agent.nodes.resolve_time import TimeResolutionError, reference_date
from app.agent.state import AgentDeps, AgentState
from app.config import SettingsError, load_settings
from app.data.clickhouse import ClickHouseRunner, QueryLimits, agent_client
from app.llm.client import LiteLLMClient
from app.llm.embeddings import LiteLLMEmbeddings
from app.packs.compiler import CompileError, load_compiled
from app.search.opensearch import OpenSearch

TABLE_ROWS = 50
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_ESCAPES = {"\n": "\\n", "\r": "\\r", "\t": "\\t"}
FAULT = "fitcherInjectedFault() AS injected_fault, "


class FaultInjectingLLM:
    """Wraps an LLM client and breaks the first SQL it generates."""

    def __init__(self, inner):
        self._inner = inner
        self._injected = False

    def structured(self, alias, prompt, schema):
        return self._inner.structured(alias, prompt, schema)

    def text(self, alias, prompt):
        reply = self._inner.text(alias, prompt)
        if alias.startswith("sql-gen") and not self._injected:
            self._injected = True
            reply = inject_fault(reply)
        return reply


def inject_fault(sql: str) -> str:
    """Add the fault after the last SELECT keyword; text that is not SQL is left as it is."""
    try:
        tokens = sqlglot.Dialect.get_or_raise("clickhouse").tokenize(sql)
    except sqlglot.errors.SqlglotError:
        return sql
    selects = [token for token in tokens if token.token_type == TokenType.SELECT]
    if not selects:
        return sql
    end = selects[-1].end + 1
    return sql[:end] + " " + FAULT + sql[end:].lstrip()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("question")
    parser.add_argument("--timezone", help="IANA time zone of the user; default UTC")
    parser.add_argument("--reference-date", type=date.fromisoformat, help="today's date for relative periods (YYYY-MM-DD)")
    parser.add_argument("--inject-sql-fault", action="store_true", help="break the first generated SQL to exercise repair")
    return parser.parse_args(argv)


def _cell(value: object) -> str:
    """One display line per cell: control characters such as line breaks are escaped."""
    if value is None:
        return ""
    return _CONTROL.sub(lambda match: _ESCAPES.get(match.group(), f"\\x{ord(match.group()):02x}"), str(value))


def format_table(columns: list[str], rows: list[list], limit: int = TABLE_ROWS) -> str:
    cells = [columns, *[[_cell(value) for value in row] for row in rows[:limit]]]
    widths = [max(len(row[index]) for row in cells) for index in range(len(columns))]
    lines = [" | ".join(value.ljust(width) for value, width in zip(row, widths, strict=True)) for row in cells]
    lines.insert(1, "-+-".join("-" * width for width in widths))
    if len(rows) > limit:
        lines.append(f"... {len(rows) - limit} more rows")
    return "\n".join(lines)


def report(state: AgentState) -> int:
    print(f"Trace: {state['trace_id']}")
    if state.get("rejection"):
        print(f"Rejected: {state['rejection']}", file=sys.stderr)
        return 2
    for number, attempt in enumerate(state.get("attempts", []), start=1):
        print(f"\nSQL attempt {number} ({attempt.alias}):\n{attempt.sql}")
        if attempt.error is not None:
            print(f"-> {attempt.error}")
    result = state.get("result")
    for warning in state.get("warnings", []):
        print(f"Warning: {warning}")
    if result is None:
        print("No result: the last SQL attempt failed.", file=sys.stderr)
        return 1
    print(f"\nResult ({result.row_count} rows{', truncated' if result.truncated else ''}):")
    print(format_table([column.name for column in result.columns], result.rows))
    if state.get("summary"):
        print(f"\nSummary:\n{state['summary']}")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        settings = load_settings()
        if not settings.active_pack:
            raise SettingsError("ACTIVE_PACK must be set")
        llm = LiteLLMClient(settings.litellm_base_url, settings.litellm_master_key)
        compiled = load_compiled(Path(settings.compiled_pack_dir), settings.active_pack)
        # Query vectors must match the indexed ones, so the compiled size wins over the environment.
        embeddings = LiteLLMEmbeddings(settings.litellm_base_url, settings.litellm_master_key, compiled.embedding_dimensions)
        deps = AgentDeps(
            llm=FaultInjectingLLM(llm) if args.inject_sql_fault else llm,
            search=OpenSearch(settings.opensearch_url),
            embeddings=embeddings,
            runner=ClickHouseRunner(agent_client(), QueryLimits.from_env()),
            compiled=compiled,
            today=args.reference_date or reference_date(args.timezone),
        )
    except (SettingsError, CompileError, TimeResolutionError, RuntimeError) as error:
        print(error, file=sys.stderr)
        return 1
    return report(run_question(args.question, deps))


if __name__ == "__main__":
    sys.exit(main())
