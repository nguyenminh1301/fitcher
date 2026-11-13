"""The latest eval result of a model for a tier, shown next to it on the Models page (DECISIONS §2, §14).

A model passed for a tier when the latest eval report of the pack that ran
the tier on it (recorded as ``provider/model``) meets the threshold and did
not regress against the baseline it was compared with; a report without a
baseline comparison proves nothing about regressions. The result informs the
choice and never gates it: any model of a configured provider may serve any
tier.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True)
class ReportSummary:
    """What eligibility needs from one ``agent_logs.eval_reports`` row."""

    report_id: str
    ts: datetime
    tiers: dict[str, str] = field(default_factory=dict)
    passed: bool = False
    # None when the run was not compared with a baseline.
    regressed: bool | None = None


@dataclass(frozen=True)
class Eligibility:
    eligible: bool
    reason: str
    # The latest report that ran the tier with the alias, when there is one.
    report_id: str | None = None
    report_ts: datetime | None = None


def eligibility(reports: Sequence[ReportSummary], tier: str, alias: str) -> Eligibility:
    """The latest result of model ``alias`` (``provider/model``) for ``tier`` from the pack's ``reports``, in any order."""
    runs = [report for report in reports if report.tiers.get(tier) == alias]
    if not runs:
        return Eligibility(False, f"no eval report ran {tier} with {alias}")
    latest = max(runs, key=lambda report: report.ts)
    found = {"report_id": latest.report_id, "report_ts": latest.ts}
    if not latest.passed:
        return Eligibility(False, "the latest eval report with it is below the threshold", **found)
    if latest.regressed is None:
        return Eligibility(False, "the latest eval report with it was not compared with the baseline", **found)
    if latest.regressed:
        return Eligibility(False, "the latest eval report with it regressed against the baseline", **found)
    return Eligibility(True, "the latest eval report with it passed without regression", **found)
