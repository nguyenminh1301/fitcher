"""Retrieve pack context for the extracted terms (DECISIONS §6 step 6).

All query texts are embedded in one ``embed`` call. Metric terms search the
glossary and metrics, dimension terms the glossary and dataset columns,
filter values the column values, and the whole question the examples and
datasets. Every query filters by role; until per-role access arrives, the
agent searches as every role of the pack.
"""

from pydantic import BaseModel, ConfigDict

from app.agent.state import AgentDeps, AgentState
from app.packs.search_indices import HYBRID_PIPELINE, alias_name, hybrid_query, value_query

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


def retrieve(state: AgentState, deps: AgentDeps) -> dict:
    extraction = state["extraction"]
    pack = deps.compiled.pack
    roles = [role.id for role in pack.policies.roles]
    metric_terms = list(dict.fromkeys([*extraction.metric_terms, *([extraction.rank_term] if extraction.rank_term else [])]))
    dimension_terms = list(dict.fromkeys(
        [*extraction.dimension_terms, *(f.column_term for f in extraction.filters if f.column_term)]
    ))
    values = list(dict.fromkeys(str(value) for f in extraction.filters for value in f.values))
    texts = list(dict.fromkeys([state["question"], *metric_terms, *dimension_terms]))
    vectors = dict(zip(texts, deps.embeddings.embed(texts), strict=True))

    def semantic(index: str, text: str) -> list[Hit]:
        hits = deps.search.search(
            alias_name(pack.name, index), hybrid_query(text, vectors[text], roles, HITS_PER_QUERY), pipeline=HYBRID_PIPELINE
        )
        return [Hit(index=index, **hit) for hit in hits]

    def lexical(text: str) -> list[Hit]:
        hits = deps.search.search(alias_name(pack.name, "column_values"), value_query(text, roles, HITS_PER_QUERY))
        return [Hit(index="column_values", **hit) for hit in hits]

    retrieval = Retrieval(
        metric_terms={term: semantic("glossary_terms", term) + semantic("metrics", term) for term in metric_terms},
        dimension_terms={term: semantic("glossary_terms", term) + semantic("datasets", term) for term in dimension_terms},
        values={value: lexical(value) for value in values},
        examples=semantic("examples", state["question"]),
        datasets=semantic("datasets", state["question"]),
    )
    return {"retrieval": retrieval}
