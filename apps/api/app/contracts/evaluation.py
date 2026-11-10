"""Eval reports as the console's Evaluation section shows them (DECISIONS §12, §15)."""

from datetime import datetime

from app.contracts.query_spec import ContractModel


class EvalLayer(ContractModel):
    passed: int
    failed: int
    not_scored: int


class FailedCase(ContractModel):
    case_id: str
    category: str
    reason: str


class EvalReportView(ContractModel):
    id: str
    ts: datetime
    # Execution match reached the threshold.
    passed: bool
    threshold: float
    layers: dict[str, EvalLayer]
    # Execution passes over scored cases per question category, as "passed/scored".
    categories: dict[str, str]
    failed_cases: list[FailedCase]
    # Compared with a baseline: whether a layer regressed; null when the run had no baseline.
    regressed: bool | None = None


class EvalRunStarted(ContractModel):
    pack: str
    running: bool
