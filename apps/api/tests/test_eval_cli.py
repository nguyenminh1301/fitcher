"""The ``jobs/eval.py`` command: scoring a pack's eval set, writing reports and choosing the exit code."""

from dataclasses import replace
from datetime import date
import json
from pathlib import Path
import shutil

from agent_fixtures import GOOD_SQL, deps, extraction_reply, good_output, routing_reply
from conftest import FIXTURE_PACK, SCHEMA_DIR
from fakes import FakeLogWriter, FakeRunner
import pytest
import yaml

from app.data.clickhouse import QueryError
from app.eval.runner import EvalRun
from jobs.eval import main

CASE_ID = "top_widgets_by_revenue"


@pytest.fixture
def packs_dir(tmp_path: Path) -> Path:
    root = tmp_path / "packs"
    shutil.copytree(FIXTURE_PACK, root / "minimal")
    shutil.copytree(SCHEMA_DIR, root / "_schema")
    return root


def _add_second_case(packs_dir: Path) -> None:
    path = packs_dir / "minimal" / "eval.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data["cases"].append({**data["cases"][0], "id": "top_widgets_again"})
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


def _answers(cases: int) -> list:
    return [routing_reply(), extraction_reply(top_n=5), GOOD_SQL, "Blue led."] * cases


def _factory(runner: FakeRunner, cases: int = 1, seen: list | None = None, logs=None):
    def build(pack: str, reference: date):
        if seen is not None:
            seen.append((pack, reference))
        return replace(deps(_answers(cases), runner=runner), logs=logs)

    return build


def _matching(cases: int = 1) -> FakeRunner:
    return FakeRunner(runs=[good_output(), good_output()] * cases)


def _mismatching(cases: int = 1) -> FakeRunner:
    return FakeRunner(runs=[good_output(rows=3), good_output()] * cases)


def _main(packs_dir: Path, *args: str, factory) -> int:
    return main(["--pack", "minimal", "--packs-dir", str(packs_dir), *args], deps_factory=factory)


def test_passing_run_prints_markdown_and_exits_0(packs_dir, capsys):
    code = _main(packs_dir, factory=_factory(_matching()))

    out = capsys.readouterr().out
    assert code == 0
    assert "# Eval report: minimal" in out
    assert f"| {CASE_ID} | top_n |" in out


def test_writes_markdown_and_json_to_output_dir(packs_dir, tmp_path):
    output = tmp_path / "out" / "eval"

    _main(packs_dir, "--output-dir", str(output), factory=_factory(_matching()))

    assert (output / "minimal-eval.md").read_text(encoding="utf-8").startswith("# Eval report: minimal")
    run = EvalRun.model_validate_json((output / "minimal-eval.json").read_text(encoding="utf-8"))
    assert [case.case_id for case in run.cases] == [CASE_ID]


def test_below_threshold_exits_1(packs_dir, capsys):
    code = _main(packs_dir, factory=_factory(_mismatching()))

    assert code == 1
    assert "not met" in capsys.readouterr().out


def test_regression_against_baseline_exits_1_and_prints_deltas(packs_dir, tmp_path, capsys):
    _add_second_case(packs_dir)
    baseline = tmp_path / "baseline.json"
    _main(packs_dir, "--output-dir", str(tmp_path), factory=_factory(_matching(2), cases=2))
    shutil.copy(tmp_path / "minimal-eval.json", baseline)
    capsys.readouterr()

    code = _main(packs_dir, "--baseline", str(baseline), "--threshold", "0", factory=_factory(_mismatching(2), cases=2))

    out = capsys.readouterr().out
    assert code == 1
    assert "| execution | 2 | 2 | 0 | -2 | REGRESSION |" in out


def test_reference_error_exits_2(packs_dir):
    runner = FakeRunner(runs=[QueryError("sql", "Unknown identifier", "qid-ref", 47), good_output()])

    assert _main(packs_dir, factory=_factory(runner)) == 2


def test_unknown_only_id_exits_2(packs_dir, capsys):
    code = _main(packs_dir, "--only", f"{CASE_ID},nope", factory=_factory(_matching()))

    assert code == 2
    assert "nope" in capsys.readouterr().err


def test_baseline_of_another_pack_exits_2(packs_dir, tmp_path, capsys):
    baseline = tmp_path / "baseline.json"
    other = EvalRun(pack="other", reference_date=date(2026, 1, 15), threshold=0.8, cases=[])
    baseline.write_text(other.model_dump_json(), encoding="utf-8")

    code = _main(packs_dir, "--baseline", str(baseline), factory=_factory(_matching()))

    assert code == 2
    assert "other" in capsys.readouterr().err


def test_pack_argument_selects_the_compiled_pack(packs_dir, monkeypatch):
    monkeypatch.setenv("ACTIVE_PACK", "another_pack")
    seen: list = []

    _main(packs_dir, factory=_factory(_matching(), seen=seen))

    assert seen == [("minimal", date(2026, 1, 15))]


def test_run_report_is_stored_in_agent_logs(packs_dir):
    logs = FakeLogWriter()
    assert _main(packs_dir, factory=_factory(_matching(), logs=logs)) == 0
    (stored,) = [record for record in logs.written if record.TABLE == "eval_reports"]
    assert (stored.pack, stored.execution_rate, stored.passed) == ("minimal", 1.0, True)
    assert len(stored.report_id) == 32
    assert json.loads(stored.report)["cases"][0]["case_id"] == CASE_ID


def test_failing_run_is_stored_as_not_passed(packs_dir):
    logs = FakeLogWriter()
    assert _main(packs_dir, factory=_factory(_mismatching(), logs=logs)) == 1
    (stored,) = [record for record in logs.written if record.TABLE == "eval_reports"]
    assert (stored.execution_rate, stored.passed) == (0.0, False)


def test_a_failed_report_write_keeps_the_exit_code(packs_dir, capsys):
    logs = FakeLogWriter(fail_tables={"eval_reports"})
    assert _main(packs_dir, factory=_factory(_matching(), logs=logs)) == 0
    assert [record.TABLE for record in logs.written].count("eval_reports") == 1
    assert "Stored report" not in capsys.readouterr().err


def test_stored_passed_is_the_threshold_result_not_the_exit_code(packs_dir, monkeypatch):
    # A baseline regression gives exit code 1 even when the execution rate meets the threshold.
    monkeypatch.setattr("jobs.eval.exit_code", lambda run, diff: 1)
    logs = FakeLogWriter()
    assert _main(packs_dir, factory=_factory(_matching(), logs=logs)) == 1
    (stored,) = [record for record in logs.written if record.TABLE == "eval_reports"]
    assert stored.passed is True


def test_cases_run_through_the_role_runners(packs_dir):
    requested: list[tuple[str, str]] = []

    def runners(pack: str):
        def runner_for(role: str):
            requested.append((pack, role))
            return _matching()
        return runner_for

    code = main(["--pack", "minimal", "--packs-dir", str(packs_dir)], deps_factory=_factory(FakeRunner()), runners_factory=runners)

    assert code == 0
    assert requested and all(item == ("minimal", "viewer") for item in requested)
