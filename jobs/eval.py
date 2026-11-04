"""Score a pack's eval set per layer and print the report.

Run with ``docker compose run --rm -v ./build/eval:/app/build/eval api python -m
jobs.eval --pack <name> --output-dir build/eval``. Each run sends billable
requests to the LiteLLM aliases at temperature 0 and runs every reference query
as the ClickHouse user of its case's role. The cases come from ``packs/<name>/eval.yaml``,
so editing them needs no recompile; the agent answers from the compiled pack
named by ``--pack``, whatever ``ACTIVE_PACK`` says. Every case's agent run is
written to ClickHouse ``agent_logs`` under the trace id kept in its JSON score,
and the JSON report itself to ``agent_logs.eval_reports``.

Each tier calls its ``MODEL_TIER_<TIER>`` default; ``--tier <tier>=<alias>``
overrides a chat tier for this run, for example ``--tier sql-small=openai-medium``.
The mapping is stored with the report together with whether the run regressed
against ``--baseline``: an alias becomes eligible for a tier on the Models page
once its latest report passes without regression (DECISIONS §2 Model tiers).
Only the tiers the run called count as evidence, and only for a run of the whole
eval set at no less than the default threshold without reference errors; any
other run is stored with no tier evidence.

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
from app.llm.tiers import CHAT_TIERS, EMBED_TIER, TierMap
from app.observability.events import EvalReportRecord, utc_now
from app.observability.log_writer import start_log_writer
from app.packs.compiler import CompileError, load_compiled
from app.packs.loader import PackValidationError, load_pack
from app.screening.screen import Screener
from app.search.client import QdrantSearch


DEFAULT_THRESHOLD = 0.8


def tier_override(value: str) -> tuple[str, str]:
    tier, separator, alias = value.partition("=")
    if not separator or not alias:
        raise argparse.ArgumentTypeError(f"expected <tier>=<alias>, got {value!r}")
    if tier not in CHAT_TIERS:
        raise argparse.ArgumentTypeError(f"--tier takes a chat tier ({', '.join(CHAT_TIERS)}), got {tier!r}")
    return tier, alias


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--pack", required=True, help="pack whose eval set runs and whose compiled pack answers")
    parser.add_argument("--only", type=lambda value: [item for item in value.split(",") if item], help="comma-separated case ids")
    parser.add_argument("--baseline", type=Path, help="JSON report of an earlier run to compare with")
    parser.add_argument("--output-dir", type=Path, help="directory for <pack>-eval.md and <pack>-eval.json")
    parser.add_argument("--timeout", type=float, default=180.0, help="seconds allowed per case; default 180")
    parser.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD, help="execution match rate the pack must reach; default 0.8")
    parser.add_argument("--packs-dir", type=Path, default=Path("packs"), help="directory of the source packs; default packs")
    parser.add_argument(
        "--tier", type=tier_override, action="append", default=[], metavar="TIER=ALIAS",
        help="run a chat tier on another catalog alias; repeat for several tiers",
    )
    return parser.parse_args(argv)


def build_deps(pack: str, reference: date, tiers: TierMap) -> AgentDeps:
    settings = load_settings()
    compiled = load_compiled(Path(settings.compiled_pack_dir), pack)
    return AgentDeps(
        llm=LiteLLMClient(settings.litellm_base_url, settings.litellm_master_key, temperature=0, tiers=tiers),
        search=QdrantSearch(settings.qdrant_url),
        # Query vectors must match the indexed ones, so the compiled size wins over the environment.
        embeddings=LiteLLMEmbeddings(
            settings.litellm_base_url, settings.litellm_master_key, compiled.embedding_dimensions,
            alias=tiers.alias(EMBED_TIER),
        ),
        # Each case replaces it with its role's runner (role_runners).
        runner=ClickHouseRunner(agent_client(pack, compiled.pack.policies.roles[0].id), QueryLimits.from_env()),
        compiled=compiled,
        today=reference,
        logs=start_log_writer(settings),
        user_id="eval",
        screener=Screener.from_settings(settings),
        screen_mode=settings.screen_mode,
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


def used_tiers(run: EvalRun) -> set[str]:
    """The tiers the run called: ``fast`` and ``embed`` in every case that ran, and each SQL generation's tier."""
    ran = any(case.trace_id for case in run.cases)
    return ({"fast", EMBED_TIER} if ran else set()) | {tier for case in run.cases for tier in case.sql_tiers}


def evidence(run: EvalRun, args: argparse.Namespace) -> tuple[dict[str, str], str | None]:
    """The tier mapping the report proves eligible, or none with the reason the run does not qualify."""
    if args.only:
        return {}, "--only runs part of the eval set"
    if args.threshold < DEFAULT_THRESHOLD:
        return {}, f"--threshold is below the default {DEFAULT_THRESHOLD:.0%}"
    if run.reference_errors:
        return {}, "a reference query failed"
    used = used_tiers(run)
    return {tier: alias for tier, alias in run.tiers.items() if tier in used}, None


def store_report(
    deps: AgentDeps, run: EvalRun, diff: BaselineDiff | None = None, tiers: dict[str, str] | None = None,
) -> None:
    """Write the JSON report to ``agent_logs.eval_reports``; a failed write is reported and changes nothing else.

    ``tiers`` is the eligibility evidence: the mapping of the tiers the run called, empty when it does not qualify.
    """
    if deps.logs is None:
        return
    report_id = uuid4().hex
    record = EvalReportRecord(
        pack=run.pack, ts=utc_now(), report_id=report_id,
        execution_rate=layer_totals(run.cases)["execution"].rate or 0.0, passed=meets_threshold(run),
        report=run.model_dump_json(), tiers=tiers or {},
        regressed=None if diff is None else bool(diff.regressed),
    )
    if deps.logs.write_now(record):
        print(f"Stored report {report_id} in agent_logs.eval_reports.", file=sys.stderr)


def main(
    argv: list[str] | None = None,
    deps_factory: Callable[[str, date, TierMap], AgentDeps] = build_deps,
    runners_factory: Callable[[str], Callable[[str], QueryRunner]] | None = None,
) -> int:
    args = parse_args(argv)
    try:
        eval_set = load_eval_set(load_pack(args.packs_dir / args.pack), args.only)
        baseline = load_baseline(args.baseline, args.pack) if args.baseline else None
        tiers = TierMap({**load_settings().model_tiers, **dict(args.tier)})
        deps = deps_factory(args.pack, eval_set.reference_date, tiers)
    except (SettingsError, CompileError, PackValidationError, EvalSetError, RuntimeError) as error:
        print(error, file=sys.stderr)
        return 2
    try:
        runner_for = runners_factory(args.pack) if runners_factory is not None else None
        run = run_eval(
            args.pack, eval_set, deps, timeout=args.timeout, threshold=args.threshold, runner_for=runner_for,
            tiers=tiers.current(),
        )
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
    proven, not_qualified = evidence(run, args)
    if not_qualified:
        print(f"The report makes no alias eligible: {not_qualified}.", file=sys.stderr)
    store_report(deps, run, diff, proven)
    return code


if __name__ == "__main__":
    sys.exit(main(runners_factory=role_runners))
