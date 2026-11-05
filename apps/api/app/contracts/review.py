"""Pack items as the console's Review and Datasets pages show them (DECISIONS §11 step 5, §15)."""

from typing import Literal

from app.contracts.query_spec import ContractModel
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


class ReviewItemPatch(ContractModel):
    body: str | None = None
    formula: str | None = None


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
