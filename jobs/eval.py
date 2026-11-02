"""Score a pack's eval set per layer and print the report.

Run with ``docker compose run --rm -v ./build/eval:/app/build/eval api python -m
jobs.eval --pack <name> --output-dir build/eval``. Each run sends billable
requests to the LiteLLM aliases at temperature 0 and runs every reference query
as the ClickHouse user of its case's role. The cases come from ``packs/<name>/eval.yaml``,
so editing them needs no recompile; the agent answers from the compiled pack
named by ``--pack``, whatever ``ACTIVE_PACK`` says. Every case's agent run is
written to ClickHouse ``agent_logs`` under the trace id kept in its JSON score,
and the JSON report itself to ``agent_logs.eval_reports``.

Exit codes: 0 when no layer regressed against ``--baseline`` and the execution
match rate meets ``--threshold``; 1 on a regression or below the threshold; 2
when the run cannot start or a reference query fails.
"""

import argparse
from collections.abc import Callable
from datetime import date
from pathlib import Path
import sys
from uuid import uuid4

from pydantic import ValidationError

from app.agent.state import AgentDeps, QueryRunner
from app.config import SettingsError, load_settings
from app.data.clickhouse import ClickHouseRunner, QueryLimits, agent_client
from app.eval.cases import EvalSetError, load_eval_set
from app.eval.report import BaselineDiff, diff_baseline, layer_totals, meets_threshold, render_markdown
from app.eval.runner import EvalRun, run_eval
from app.llm.client import LiteLLMClient
from app.llm.embeddings import LiteLLMEmbeddings
from app.observability.events import EvalReportRecord, utc_now
from app.observability.log_writer import start_log_writer
from app.packs.compiler import CompileError, load_compiled
from app.packs.loader import PackValidationError, load_pack
from app.search.opensearch import OpenSearch


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--pack", required=True, help="pack whose eval set runs and whose compiled pack answers")
    parser.add_argument("--only", type=lambda value: [item for item in value.split(",") if item], help="comma-separated case ids")
    parser.add_argument("--baseline", type=Path, help="JSON report of an earlier run to compare with")
    parser.add_argument("--output-dir", type=Path, help="directory for <pack>-eval.md and <pack>-eval.json")
    parser.add_argument("--timeout", type=float, default=180.0, help="seconds allowed per case; default 180")
    parser.add_argument("--threshold", type=float, default=0.8, help="execution match rate the pack must reach; default 0.8")
    parser.add_argument("--packs-dir", type=Path, default=Path("packs"), help="directory of the source packs; default packs")
    return parser.parse_args(argv)


def build_deps(pack: str, reference: date) -> AgentDeps:
    settings = load_settings()
    compiled = load_compiled(Path(settings.compiled_pack_dir), pack)
    return AgentDeps(
        llm=LiteLLMClient(settings.litellm_base_url, settings.litellm_master_key, temperature=0),
        search=OpenSearch(settings.opensearch_url),
        # Query vectors must match the indexed ones, so the compiled size wins over the environment.
        embeddings=LiteLLMEmbeddings(settings.litellm_base_url, settings.litellm_master_key, compiled.embedding_dimensions),
        # Each case replaces it with its role's runner (role_runners).
        runner=ClickHouseRunner(agent_client(pack, compiled.pack.policies.roles[0].id), QueryLimits.from_env()),
        compiled=compiled,
        today=reference,
        logs=start_log_writer(settings),
        user_id="eval",
    )


def role_runners(pack: str) -> Callable[[str], QueryRunner]:
    """One runner per role, connected as that role's ClickHouse user and reused across its cases."""
    limits = QueryLimits.from_env()
    runners: dict[str, QueryRunner] = {}

    def runner_for(role: str) -> QueryRunner:
        if role not in runners:
            runners[role] = ClickHouseRunner(agent_client(pack, role), limits)
        return runners[role]

    return runner_for


def load_baseline(path: Path, pack: str) -> EvalRun:
    try:
        baseline = EvalRun.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValidationError) as error:
        raise EvalSetError(f"cannot read baseline {path}: {type(error).__name__}") from error
    if baseline.pack != pack:
        raise EvalSetError(f"baseline {path} is a run of pack {baseline.pack}, not {pack}")
    return baseline


def exit_code(run: EvalRun, diff: BaselineDiff | None) -> int:
    if run.reference_errors:
        return 2
    if (diff is not None and diff.regressed) or not meets_threshold(run):
        return 1
    return 0


def store_report(deps: AgentDeps, run: EvalRun) -> None:
    """Write the JSON report to ``agent_logs.eval_reports``; a failed write is reported and changes nothing else."""
    if deps.logs is None:
        return
    report_id = uuid4().hex
    record = EvalReportRecord(
        pack=run.pack, ts=utc_now(), report_id=report_id,
        execution_rate=layer_totals(run.cases)["execution"].rate or 0.0, passed=meets_threshold(run),
        report=run.model_dump_json(),
    )
    if deps.logs.write_now(record):
        print(f"Stored report {report_id} in agent_logs.eval_reports.", file=sys.stderr)


def main(
    argv: list[str] | None = None,
    deps_factory: Callable[[str, date], AgentDeps] = build_deps,
    runners_factory: Callable[[str], Callable[[str], QueryRunner]] | None = None,
) -> int:
    args = parse_args(argv)
    try:
        eval_set = load_eval_set(load_pack(args.packs_dir / args.pack), args.only)
        baseline = load_baseline(args.baseline, args.pack) if args.baseline else None
        deps = deps_factory(args.pack, eval_set.reference_date)
    except (SettingsError, CompileError, PackValidationError, EvalSetError, RuntimeError) as error:
        print(error, file=sys.stderr)
        return 2
    try:
        runner_for = runners_factory(args.pack) if runners_factory is not None else None
        run = run_eval(args.pack, eval_set, deps, timeout=args.timeout, threshold=args.threshold, runner_for=runner_for)
    finally:
        if deps.logs is not None:
            deps.logs.close()
    diff = diff_baseline(baseline, run) if baseline is not None else None
    markdown = render_markdown(run, diff)
    print(markdown)
    if args.output_dir:
        args.output_dir.mkdir(parents=True, exist_ok=True)
        (args.output_dir / f"{args.pack}-eval.md").write_text(markdown, encoding="utf-8", newline="\n")
        (args.output_dir / f"{args.pack}-eval.json").write_text(
            run.model_dump_json(indent=2) + "\n", encoding="utf-8", newline="\n"
        )
    code = exit_code(run, diff)
    store_report(deps, run)
    return code


if __name__ == "__main__":
    sys.exit(main(runners_factory=role_runners))
