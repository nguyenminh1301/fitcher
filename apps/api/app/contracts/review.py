"""Pack items as the console's Review and Datasets pages show them (DECISIONS §11 step 5, §15)."""

from typing import Literal

from pydantic import Field

from app.contracts.query_spec import ContractModel, Scalar
from app.contracts.result import Result


class ReviewEvidence(ContractModel):
    """The evidence shown first: a cited document, else the first entry."""

    source: str
    quote: str | None = None
    # The cited document was deleted; the reviewer decides whether the item still stands.
    deleted: bool = False


class EvidenceRef(ContractModel):
    kind: Literal["manual", "profile", "doc", "error", "trace"]
    ref: str


class SpecFilter(ContractModel):
    column: str = Field(min_length=1)
    op: Literal["=", "!=", "in", "not in"]
    values: list[Scalar] = Field(min_length=1)


class ReviewedSpec(ContractModel):
    """The QuerySpec a proposal's example settles for its question, without periods (DECISIONS §6 step 7)."""

    metric_ids: list[str] = Field(min_length=1)
    dataset: str = Field(min_length=1)
    dimensions: list[str] = []
    filters: list[SpecFilter] = []
    top_n: int | None = Field(default=None, ge=1)
    rank_by: str | None = None


class ReviewItem(ContractModel):
    # ``<file stem>.<item id>``, for example ``metrics.gross_total``.
    id: str
    file: str
    name: str
    # The api lists pack items; examples proposed from feedback join them in Phase 12.
    kind: Literal["item", "proposal"]
    status: Literal["draft", "approved"]
    confidence: float
    # The item's text: a description, definition or question.
    body: str
    # A metric's sql_expr, an example's sql or an eval case's expected_sql.
    formula: str | None = None
    evidence: ReviewEvidence | None = None
    evidence_refs: list[EvidenceRef] = []
    test_result: Result | None = None
    # A proposal's spec: the run's, until the reviewer edits it; only a reviewed spec is approved into the example.
    spec: ReviewedSpec | None = None
    spec_reviewed: bool = False


class ReviewItemPatch(ContractModel):
    body: str | None = None
    formula: str | None = None
    # Proposals only: a spec marks it reviewed; spec_reviewed false leaves it out of the approved example.
    spec: ReviewedSpec | None = None
    spec_reviewed: bool | None = None


class DatasetColumnView(ContractModel):
    name: str
    type: str
    role: str
    description: str


class DatasetView(ContractModel):
    id: str
    description: str
    grain: str
    time_column: str
    # Pack roles granted the dataset in policies.yaml, aggregate-only grants included.
    readable_roles: list[str]
    columns: list[DatasetColumnView]
