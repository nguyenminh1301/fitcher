"""Eval reports per layer and category, and the regression check against a baseline."""

from datetime import date

from app.eval.report import category_totals, diff_baseline, layer_totals, meets_threshold, render_markdown, routing_totals
from app.eval.runner import EvalRun
from app.eval.scorers import LAYERS, CaseScore, LayerScore

PASS = LayerScore(status="pass")
SKIP = LayerScore(status="not_scored", reason="router not built")


def fail(reason: str = "wrong value") -> LayerScore:
    return LayerScore(status="fail", reason=reason)


def case(case_id: str, execution: LayerScore = PASS, category: str = "top_n", **layers: LayerScore) -> CaseScore:
    scores = {"intent": SKIP, "extraction": PASS, "retrieval": LayerScore(status="pass", recall=1.0), "execution": execution}
    return CaseScore(
        case_id=case_id, category=category, question=f"Question {case_id}", active=True, layers={**scores, **layers},
    )


def inactive(case_id: str) -> CaseScore:
    skipped = LayerScore(status="not_scored", reason="not yet scored: active from phase 6")
    return CaseScore(
        case_id=case_id, category="out_of_scope", question="Weather?", active=False, layers=dict.fromkeys(LAYERS, skipped),
    )


def run(*cases: CaseScore, threshold: float = 0.8, reference_errors: list[str] | None = None) -> EvalRun:
    return EvalRun(
        pack="minimal", reference_date=date(2026, 1, 15), threshold=threshold, cases=list(cases),
        reference_errors=reference_errors or [],
    )


def test_layer_rates_ignore_not_scored_cases():
    totals = layer_totals([case("a"), case("b", fail()), inactive("c")])

    assert (totals["execution"].passed, totals["execution"].failed, totals["execution"].not_scored) == (1, 1, 1)
    assert totals["execution"].rate == 0.5
    assert totals["intent"].rate is None


def test_category_totals_group_layers_by_category():
    totals = category_totals([case("a"), case("b", fail(), category="string_filter")])

    assert totals["top_n"]["execution"].passed == 1
    assert totals["string_filter"]["execution"].failed == 1


def test_markdown_has_layer_category_and_case_tables():
    report = render_markdown(run(case("a"), case("b", fail("no column matches measure revenue")), inactive("c")))

    for heading in ("# Eval report: minimal", "## Layers", "## Categories", "## Cases"):
        assert heading in report
    assert "Reference date: 2026-01-15" in report
    assert "threshold 80%: not met" in report
    assert "| execution | 1 | 1 | 1 | 50% |" in report
    assert "| retrieval | 2 | 0 | 1 | 100% | 1.00 |" in report
    case_rows = [line for line in report.splitlines() if line.startswith("| a |") or line.startswith("| b |")
                 or line.startswith("| c |")]
    assert len(case_rows) == 3
    assert "no column matches measure revenue" in report
    assert "## Baseline" not in report
    assert "## Reference errors" not in report


def test_markdown_lists_reference_errors_and_case_errors():
    crashed = case("a", fail("KeyError: 'payload'")).model_copy(update={"error": "KeyError: 'payload'"})

    report = render_markdown(run(crashed, reference_errors=["b: Unknown identifier"]))

    assert "## Reference errors" in report
    assert "- b: Unknown identifier" in report
    assert "KeyError: 'payload'" in report


def test_markdown_escapes_pipes_in_reasons():
    report = render_markdown(run(case("a", fail("expected a|b\ngot c"))))

    row = next(line for line in report.splitlines() if line.startswith("| a |"))
    assert "a\\|b got c" in row


def test_baseline_compares_only_common_cases():
    baseline = run(case("kept"), case("removed"))
    current = run(case("kept", fail()), case("added"))

    diff = diff_baseline(baseline, current)

    execution = diff.layers["execution"]
    assert (execution.common, execution.baseline_passed, execution.current_passed, execution.drop) == (1, 1, 0, 1)


def test_not_scored_in_either_run_is_not_compared():
    diff = diff_baseline(run(inactive("a"), case("b")), run(case("a", fail()), case("b")))

    assert diff.layers["execution"].common == 1


def test_drop_of_one_case_is_not_a_regression_but_two_is():
    baseline = run(case("a"), case("b"), case("c"))

    assert diff_baseline(baseline, run(case("a", fail()), case("b"), case("c"))).regressed == []
    two_down = diff_baseline(baseline, run(case("a", fail()), case("b", fail()), case("c")))
    assert two_down.regressed == ["execution"]


def test_markdown_shows_baseline_deltas_and_regressions():
    baseline = run(case("a"), case("b"), case("c"))
    current = run(case("a", fail()), case("b", fail()), case("c"))

    report = render_markdown(current, diff_baseline(baseline, current))

    assert "## Baseline" in report
    assert "| execution | 3 | 3 | 1 | -2 | REGRESSION |" in report


def test_json_round_trips():
    original = run(case("a"), inactive("b"), reference_errors=["c: Unknown identifier"])

    assert EvalRun.model_validate_json(original.model_dump_json(indent=2)) == original


def test_threshold_uses_execution_rate():
    four_of_five = run(*(case(str(i)) for i in range(4)), case("5", fail()))
    three_of_five = run(*(case(str(i)) for i in range(3)), case("4", fail()), case("5", fail()))

    assert meets_threshold(four_of_five) is True
    assert meets_threshold(three_of_five) is False
    assert meets_threshold(run(inactive("a"))) is False


def test_routing_totals_count_the_small_share_and_its_escalations():
    def scored(tiers):
        return CaseScore(case_id="c", category="top_n", question="q", active=True, layers={}, sql_tiers=tiers)

    totals = routing_totals([scored(["sql-small"]), scored(["sql-small", "sql-gen"]), scored(["sql-gen"]), scored([])])

    assert (totals.generated, totals.small_first, totals.escalated) == (3, 2, 1)
    assert (totals.small_share, totals.escalation_rate) == (2 / 3, 0.5)
