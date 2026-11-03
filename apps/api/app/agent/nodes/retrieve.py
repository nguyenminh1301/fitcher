"""Retrieve pack context for the extracted terms (DECISIONS §6 step 6).

All query texts are embedded in one ``embed`` call. Metric terms search the
glossary and metrics, dimension terms the glossary and dataset columns,
filter values the column values, and the whole question the examples and
datasets, and the metrics too when it names no measure. The candidates for the question's own terms (metrics, dimensions and
filter values) are searched across every role of the pack, so a term is
resolved to what it means and the gate can deny it, instead of being replaced
by the closest item the asking role may read. The context shown to the SQL
generator (examples) and the dataset hits are filtered by the asking role.
Retrieval is a noise filter; the gate, the guard and ClickHouse enforce access.
"""

from pydantic import BaseModel, ConfigDict

from app.agent.state import AgentDeps, AgentState
from app.llm.embeddings import EmbeddingError
from app.packs.search_indices import HYBRID_PIPELINE, alias_name, hybrid_query, value_query
from app.search.opensearch import SearchError

HITS_PER_QUERY = 5


class Hit(BaseModel):
    model_config = ConfigDict(frozen=True)

    index: str
    id: str
    score: float
    source: dict


class Retrieval(BaseModel):
    model_config = ConfigDict(frozen=True)

    metric_terms: dict[str, list[Hit]] = {}
    dimension_terms: dict[str, list[Hit]] = {}
    values: dict[str, list[Hit]] = {}
    examples: list[Hit] = []
    datasets: list[Hit] = []
    # Metrics closest to a question that names no measure, readable by the asking role: a clarify's options.
    question_metrics: list[Hit] = []


def retrieve(state: AgentState, deps: AgentDeps) -> dict:
    try:
        return {"retrieval": _retrieve(state, deps)}
    except (EmbeddingError, SearchError) as error:
        return {"rejection": f"the pack context could not be retrieved: {error}"}


def _retrieve(state: AgentState, deps: AgentDeps) -> "Retrieval":
    extraction = state["extraction"]
    pack = deps.compiled.pack
    every_role = [role.id for role in pack.policies.roles]
    asking_role = [deps.role]
    metric_terms = list(dict.fromkeys([*extraction.metric_terms, *([extraction.rank_term] if extraction.rank_term else [])]))
    dimension_terms = list(dict.fromkeys(
        [*extraction.dimension_terms, *(f.column_term for f in extraction.filters if f.column_term)]
    ))
    values = list(dict.fromkeys(str(value) for f in extraction.filters for value in f.values))
    texts = list(dict.fromkeys([state["question"], *metric_terms, *dimension_terms]))
    vectors = dict(zip(texts, deps.embeddings.embed(texts), strict=True))

    def semantic(index: str, text: str, roles: list[str]) -> list[Hit]:
        hits = deps.search.search(
            alias_name(pack.name, index), hybrid_query(text, vectors[text], roles, HITS_PER_QUERY), pipeline=HYBRID_PIPELINE
        )
        return [Hit(index=index, **hit) for hit in hits]

    def lexical(text: str) -> list[Hit]:
        hits = deps.search.search(alias_name(pack.name, "column_values"), value_query(text, every_role, HITS_PER_QUERY))
        return [Hit(index="column_values", **hit) for hit in hits]

    def term(index: str, text: str) -> list[Hit]:
        return semantic("glossary_terms", text, every_role) + semantic(index, text, every_role)

    return Retrieval(
        metric_terms={text: term("metrics", text) for text in metric_terms},
        dimension_terms={text: term("datasets", text) for text in dimension_terms},
        values={value: lexical(value) for value in values},
        examples=semantic("examples", state["question"], asking_role),
        datasets=semantic("datasets", state["question"], asking_role),
        question_metrics=[] if metric_terms else semantic("metrics", state["question"], asking_role),
    )
