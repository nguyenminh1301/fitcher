"""Map extracted terms to pack metrics and columns and build the QuerySpec (DECISIONS §6 step 7).

Resolution is deterministic. A term first matches a glossary term or alias,
a metric id or name, or a column name exactly, ignoring case, diacritics,
punctuation and a plural "s"; otherwise the retrieval hits decide. A ranking
term ("best-selling") must match exactly or through a business-profile
convention, so a vague "best" is never guessed. Without a clarify branch yet,
a measure whose two best candidates score almost alike is refused, as are
metrics from different datasets and terms that match nothing.

The coverage check compares each period with the dataset's compiled date
range and adds warnings; it never blocks the question.
"""

from collections.abc import Iterable
from datetime import date
import re
import unicodedata

from pydantic import ValidationError

from app.agent.nodes.retrieve import Hit, Retrieval
from app.agent.state import AgentDeps, AgentState
from app.contracts.query_spec import Filter, Period, QuerySpec
from app.packs.compiler import CompiledPack, DateCoverage
from app.packs.models import Dataset

# A runner-up scoring at least this share of the best candidate makes a term ambiguous.
AMBIGUITY_RATIO = 0.9


class SpecRejected(Exception):
    """The question cannot be mapped to one unambiguous QuerySpec."""


def fold(text: str) -> str:
    """Lowercase, strip diacritics (including đ) and collapse punctuation to single spaces."""
    text = unicodedata.normalize("NFKD", text.replace("đ", "d").replace("Đ", "D"))
    text = "".join(char for char in text if not unicodedata.combining(char)).lower()
    return " ".join(re.split(r"[^a-z0-9]+", text)).strip()


def _forms(term: str) -> set[str]:
    folded = fold(term)
    forms = {folded}
    if folded.endswith("es"):
        forms.add(folded[:-2])
    if folded.endswith("s"):
        forms.add(folded[:-1])
    return forms


class _Catalog:
    """Exact-match lookups over the approved pack."""

    def __init__(self, compiled: CompiledPack):
        pack = compiled.pack
        self.pack = pack
        self.datasets = {dataset.id: dataset for dataset in pack.datasets.datasets}
        self.metrics = {metric.id: metric for metric in pack.metrics.metrics}
        self.terms = {}
        for term in pack.glossary.terms:
            for name in [term.term, term.id, *term.aliases.vi, *term.aliases.en]:
                self.terms.setdefault(fold(name), []).append(term)
        self.conventions = {fold(convention.id): convention.metric for convention in pack.business_profile.conventions}

    def glossary(self, term: str):
        return [entry for form in _forms(term) for entry in self.terms.get(form, [])]

    def exact_metrics(self, term: str) -> list[str]:
        found = [target.metric for entry in self.glossary(term) for target in entry.targets if target.metric]
        forms = _forms(term)
        found += [metric.id for metric in self.metrics.values() if fold(metric.id) in forms or fold(metric.name) in forms]
        return list(dict.fromkeys(found))

    def convention_metric(self, term: str) -> str | None:
        """Metric of a convention named by the term or by a glossary term sharing its id."""
        for form in _forms(term):
            if form in self.conventions:
                return self.conventions[form]
        for entry in self.glossary(term):
            if fold(entry.id) in self.conventions:
                return self.conventions[fold(entry.id)]
        return None

    def exact_columns(self, term: str, dataset: Dataset) -> list[str]:
        names = {column.name for column in dataset.columns}
        found = [
            target.column for entry in self.glossary(term) for target in entry.targets
            if target.dataset == dataset.id and target.column in names and target.kind == "column"
        ]
        forms = _forms(term)
        found += [column.name for column in dataset.columns if fold(column.name) in forms]
        return list(dict.fromkeys(found))


def _best(candidates: dict[str, float], what: str, term: str) -> str | None:
    if not candidates:
        return None
    ranked = sorted(candidates.items(), key=lambda item: -item[1])
    if len(ranked) > 1 and ranked[1][1] >= AMBIGUITY_RATIO * ranked[0][1]:
        raise SpecRejected(f"'{term}' could mean the {what} {ranked[0][0]} or {ranked[1][0]}")
    return ranked[0][0]


def _metric_from_hits(hits: Iterable[Hit]) -> dict[str, float]:
    scores: dict[str, float] = {}
    for hit in hits:
        if hit.index == "metrics":
            ids = [hit.id]
        else:
            ids = [target["metric"] for target in hit.source.get("payload", {}).get("targets", []) if target.get("metric")]
        for metric_id in ids:
            scores[metric_id] = max(scores.get(metric_id, 0.0), hit.score)
    return scores


def _resolve_metric(term: str, catalog: _Catalog, retrieval: Retrieval) -> str:
    exact = catalog.exact_metrics(term)
    if len(exact) == 1:
        return exact[0]
    if len(exact) > 1:
        convention = catalog.convention_metric(term)
        if convention in exact:
            return convention
        raise SpecRejected(f"'{term}' could mean the metrics {', '.join(exact)}")
    found = _best(_metric_from_hits(retrieval.metric_terms.get(term, [])), "metrics", term)
    if found is None or found not in catalog.metrics:
        raise SpecRejected(f"no metric matches '{term}'")
    return found


def _resolve_rank_metric(term: str, catalog: _Catalog) -> str:
    exact = catalog.exact_metrics(term)
    if len(exact) == 1:
        return exact[0]
    convention = catalog.convention_metric(term)
    if convention is not None:
        return convention
    raise SpecRejected(f"'{term}' does not say which measure to rank by")


def _column_from_hits(hits: Iterable[Hit], dataset: Dataset) -> dict[str, float]:
    names = {column.name for column in dataset.columns}
    scores: dict[str, float] = {}
    for hit in hits:
        payload = hit.source.get("payload", {})
        if hit.index == "datasets" and hit.source.get("dataset") == dataset.id and payload.get("column") in names:
            columns = [payload["column"]]
        elif hit.index == "glossary_terms":
            columns = [
                target["column"] for target in payload.get("targets", [])
                if target.get("kind") == "column" and target.get("dataset") == dataset.id and target.get("column") in names
            ]
        else:
            columns = []
        for column in columns:
            scores[column] = max(scores.get(column, 0.0), hit.score)
    return scores


def _resolve_column(term: str, dataset: Dataset, catalog: _Catalog, retrieval: Retrieval) -> str:
    exact = catalog.exact_columns(term, dataset)
    if len(exact) == 1:
        return exact[0]
    if len(exact) > 1:
        raise SpecRejected(f"'{term}' could mean the columns {', '.join(exact)}")
    found = _best(_column_from_hits(retrieval.dimension_terms.get(term, []), dataset), "columns", term)
    if found is None:
        raise SpecRejected(f"no column of {dataset.id} matches '{term}'")
    return found


def _resolve_value(value: object, column: str | None, dataset: Dataset, catalog: _Catalog, retrieval: Retrieval):
    """Return ``(column, canonical value)`` for one filter value."""
    for entry in catalog.glossary(str(value)):
        for target in entry.targets:
            if target.kind == "value" and target.dataset == dataset.id and column in (None, target.column):
                return target.column, target.value
    hits = [
        hit for hit in retrieval.values.get(str(value), [])
        if hit.source.get("dataset") == dataset.id and column in (None, hit.source.get("column"))
    ]
    if hits:
        best = max(hits, key=lambda hit: hit.score)
        return best.source["column"], best.source["payload"]["value"]
    if column is not None and any(c.name == column and c.type != "string" for c in dataset.columns):
        return column, value
    raise SpecRejected(f"no value of {dataset.id} matches '{value}'")


def coverage_warnings(periods: list[Period], dataset: str, coverage: DateCoverage | None) -> list[str]:
    if coverage is None or coverage.rows == 0 or coverage.min_date is None or coverage.max_date is None:
        return [f"{dataset} has no data"]
    low, high = date.fromisoformat(coverage.min_date), date.fromisoformat(coverage.max_date)
    warnings = []
    for period in periods:
        last = period.end.toordinal() - 1
        if period.start > high or last < low.toordinal():
            warnings.append(f"{period.label} is outside the data, which covers {low} to {high}")
        elif period.start < low or last > high.toordinal():
            warnings.append(f"{period.label} is only partly covered by the data, which covers {low} to {high}")
    return warnings


def make_spec(state: AgentState, compiled: CompiledPack) -> QuerySpec:
    extraction = state["extraction"]
    retrieval = state["retrieval"]
    periods = state["periods"]
    catalog = _Catalog(compiled)

    metric_ids = [_resolve_metric(term, catalog, retrieval) for term in extraction.metric_terms]
    rank_by = _resolve_rank_metric(extraction.rank_term, catalog) if extraction.rank_term else None
    if rank_by is not None and rank_by not in metric_ids:
        metric_ids.append(rank_by)
    metric_ids = list(dict.fromkeys(metric_ids))
    datasets = {catalog.metrics[metric_id].dataset for metric_id in metric_ids}
    if len(datasets) != 1:
        raise SpecRejected(f"the metrics {', '.join(metric_ids)} come from different datasets")
    dataset = catalog.datasets[datasets.pop()]

    dimensions = [_resolve_column(term, dataset, catalog, retrieval) for term in extraction.dimension_terms]
    if state.get("time_grain") and dataset.time_column not in dimensions:
        dimensions.append(dataset.time_column)
    filters = []
    for extracted in extraction.filters:
        column = _resolve_column(extracted.column_term, dataset, catalog, retrieval) if extracted.column_term else None
        resolved = [_resolve_value(value, column, dataset, catalog, retrieval) for value in extracted.values]
        columns = {name for name, _ in resolved}
        if len(columns) != 1:
            raise SpecRejected(f"the values {extracted.values} belong to different columns")
        values = [value for _, value in resolved]
        filters.append(Filter(column=columns.pop(), op=extracted.op, value=values if extracted.op in ("in", "not in") else values[0]))

    if rank_by is None and extraction.top_n is not None:
        rank_by = metric_ids[0]
    warnings = []
    compare = extraction.compare and len(periods) > 1
    if extraction.compare and not compare:
        warnings.append("only one period was named, so nothing is compared")
    rank_period = max(periods, key=lambda period: period.start).label if rank_by and len(periods) > 1 else None
    warnings += coverage_warnings(periods, dataset.id, compiled.coverage.get(dataset.id))
    return QuerySpec(
        metric_ids=metric_ids, dimensions=list(dict.fromkeys(dimensions)), periods=periods, filters=filters,
        top_n=extraction.top_n, rank_by=rank_by, rank_period=rank_period, compare=compare, dataset=dataset.id,
        warnings=warnings,
    )


def build_spec(state: AgentState, deps: AgentDeps) -> dict:
    try:
        spec = make_spec(state, deps.compiled)
    except SpecRejected as rejection:
        return {"rejection": str(rejection)}
    except ValidationError as error:
        return {"rejection": f"the question does not form a valid query: {error.errors()[0]['msg']}"}
    return {"spec": spec, "warnings": [*state.get("warnings", []), *spec.warnings]}
