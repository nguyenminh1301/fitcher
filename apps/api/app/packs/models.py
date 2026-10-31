"""Typed Domain Pack models, kept identical to the JSON Schemas in packs/_schema.

The schemas validate pack files first and carry value constraints such as
patterns and bounds; these models give the engine typed access to the same
fields. A test compares both so they cannot drift apart.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict


class PackModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Evidence(PackModel):
    kind: Literal["manual", "profile", "doc", "error", "trace"]
    ref: str


class Draftable(PackModel):
    """Fields every item carries so drafted items can be reviewed before compiling."""

    status: Literal["draft", "approved"]
    evidence: list[Evidence]
    confidence: float


class Convention(Draftable):
    id: str
    description: str
    metric: str


class BusinessProfile(PackModel):
    name: str
    display_name: str
    industry: str
    currency: str
    fiscal_year_start_month: int
    conventions: list[Convention]


class Column(PackModel):
    name: str
    type: Literal["string", "number", "date", "datetime", "boolean"]
    role: Literal["dimension", "measure", "time"]
    description: str
    indexable: bool = False


class Dataset(Draftable):
    id: str
    description: str
    grain: str
    time_column: str
    allowed_roles: list[str]
    columns: list[Column]


class DatasetsFile(PackModel):
    datasets: list[Dataset]


class Aliases(PackModel):
    vi: list[str]
    en: list[str]


class GlossaryTarget(PackModel):
    kind: Literal["metric", "column", "value"]
    metric: str | None = None
    dataset: str | None = None
    column: str | None = None
    value: str | None = None


class GlossaryTerm(Draftable):
    id: str
    term: str
    definition: str
    aliases: Aliases
    targets: list[GlossaryTarget]


class GlossaryFile(PackModel):
    terms: list[GlossaryTerm]


class Metric(Draftable):
    id: str
    name: str
    description: str
    dataset: str
    sql_expr: str
    grain: Literal["day", "week", "month", "quarter", "year"]
    unit: Literal["currency", "count", "ratio", "percent", "days", "number"]
    owner: str


class MetricsFile(PackModel):
    metrics: list[Metric]


class JoinColumns(PackModel):
    from_column: str
    to_column: str


class Relationship(Draftable):
    id: str
    description: str
    from_dataset: str
    to_dataset: str
    on: list[JoinColumns]
    cardinality: Literal["one_to_one", "many_to_one", "one_to_many"]


class RelationshipsFile(PackModel):
    relationships: list[Relationship]


class Example(Draftable):
    id: str
    question: str
    language: str
    sql: str
    datasets: list[str]
    metrics: list[str]


class ExamplesFile(PackModel):
    examples: list[Example]


class DatasetGrant(PackModel):
    dataset: str
    columns: list[str]
    row_filter: str | None = None


class Role(Draftable):
    id: str
    description: str
    datasets: list[DatasetGrant]


class PoliciesFile(PackModel):
    roles: list[Role]


class EvalPeriod(PackModel):
    label: str
    start: str
    end: str


class EvalExpected(PackModel):
    intent: Literal["data_query", "metadata_qa", "chart_edit", "out_of_scope"]
    outcome: Literal["answer", "clarify", "deny"]
    metrics: list[str] = []
    periods: list[EvalPeriod] = []
    top_n: int | None = None
    rank_by: str | None = None
    dataset: str | None = None
    columns: list[str] = []


class EvalCase(Draftable):
    id: str
    question: str
    language: str
    category: Literal[
        "two_period_compare", "top_n", "string_filter", "monthly_trend", "ambiguous", "unauthorized", "out_of_scope"
    ]
    role: str
    expected: EvalExpected
    expected_sql: str | None = None
    active_from_phase: int | None = None


class EvalFile(PackModel):
    cases: list[EvalCase]


class Pack(PackModel):
    name: str
    business_profile: BusinessProfile
    datasets: DatasetsFile
    glossary: GlossaryFile
    metrics: MetricsFile
    relationships: RelationshipsFile
    examples: ExamplesFile
    policies: PoliciesFile
    eval: EvalFile


# Pack file name -> model of its whole content, in loading order.
PACK_FILES: dict[str, type[PackModel]] = {
    "business_profile.yaml": BusinessProfile,
    "datasets.yaml": DatasetsFile,
    "glossary.yaml": GlossaryFile,
    "metrics.yaml": MetricsFile,
    "relationships.yaml": RelationshipsFile,
    "examples.yaml": ExamplesFile,
    "policies.yaml": PoliciesFile,
    "eval.yaml": EvalFile,
}
