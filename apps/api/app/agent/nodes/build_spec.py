"""Map extracted terms to pack metrics and columns and build the QuerySpec (DECISIONS §6 step 7).

Resolution is deterministic. A term first matches a glossary term or alias,
a metric id or name, or a column name exactly, ignoring case, diacritics,
punctuation and a plural "s"; otherwise the retrieval hits decide. A ranking
term ("best-selling") must match exactly or through a business-profile
convention, so a vague "best" alone is never guessed; next to a named measure
("top 5 brands by units sold") it ranks by that measure. What the question leaves
open becomes a ``Need`` that the gate asks about: no measure, a ranking word
alone, a term whose best candidates score almost alike, or no period. Metrics
from different datasets and terms or values that match nothing are refused.

A metric term that matches no metric but contains a glossary term naming only
values ("bourbon sales dollars") is split: the rest of the words name the
metric and the values become a filter, so the values are never silently lost.

An approved example that asks the same question (compared after folding) and
carries a reviewed spec settles the metrics, dataset, dimensions, filters, top
N and ranking instead (DECISIONS §6 step 7); the periods and time grain still
come from the question. The examples were retrieved for the asking role.

The coverage check compares each period with the dataset's compiled date
range and adds warnings; it never blocks the question.
"""

from collections.abc import Iterable
from datetime import date

from pydantic import ValidationError

from app.agent.nodes.clarify import Need
from app.agent.nodes.retrieve import Hit, Retrieval
from app.agent.state import AgentDeps, AgentState
from app.contracts.query_spec import Filter, Period, QuerySpec
from app.packs.compiler import CompiledPack, DateCoverage
from app.packs.models import Dataset, GlossaryTerm
from app.text import fold

# A runner-up scoring at least this share of the best candidate makes a term ambiguous.
AMBIGUITY_RATIO = 0.9


class SpecRejected(Exception):
    """The question cannot be mapped to one unambiguous QuerySpec."""


class NeedsChoice(SpecRejected):
    """The question leaves open what ``need`` describes; the user is asked instead of refused."""

    def __init__(self, need: Need):
        super().__init__(f"the question leaves the {need.kind} open")
        self.need = need


class _Tie(Exception):
    """Several candidates score almost alike; ``candidates`` holds them best first."""

    def __init__(self, candidates: list[str]):
        self.candidates = candidates


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
        # Glossary terms that name only values, longest name first, so "straight bourbon" wins over "bourbon".
        named = {
            (tuple(fold(name).split()), term.id): term for term in pack.glossary.terms
            if term.targets and all(target.kind == "value" for target in term.targets)
            for name in [term.term, *term.aliases.vi, *term.aliases.en] if fold(name)
        }
        self.value_terms = sorted(((words, term) for (words, _), term in named.items()), key=lambda item: -len(item[0]))

    def split_values(self, term: str) -> tuple[str, list[GlossaryTerm]]:
        """The words left after removing value-naming glossary terms, and those terms; ``(term, [])`` if none or nothing is left."""
        words = fold(term).split()
        found: dict[str, GlossaryTerm] = {}
        for name, entry in self.value_terms:
            for start in range(len(words) - len(name) + 1):
                if tuple(words[start:start + len(name)]) == name:
                    words = words[:start] + words[start + len(name):]
                    found.setdefault(entry.id, entry)
                    break
        if not found or not words:
            return term, []
        return " ".join(words), list(found.values())

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


def _ranked(candidates: dict[str, float]) -> list[str]:
    return [name for name, _ in sorted(candidates.items(), key=lambda item: -item[1])]


def _best(candidates: dict[str, float]) -> str | None:
    if not candidates:
        return None
    ranked = sorted(candidates.items(), key=lambda item: -item[1])
    if len(ranked) > 1 and ranked[1][1] >= AMBIGUITY_RATIO * ranked[0][1]:
        raise _Tie([name for name, score in ranked if score >= AMBIGUITY_RATIO * ranked[0][1]])
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


def _resolve_metric(term: str, catalog: _Catalog, retrieval: Retrieval, words: str | None = None) -> str:
    """Resolve ``term``; ``words`` replaces it for exact matching when value terms were split off it."""
    exact = catalog.exact_metrics(words or term)
    if len(exact) == 1:
        return exact[0]
    if len(exact) > 1:
        convention = catalog.convention_metric(term)
        if convention in exact:
            return convention
        raise NeedsChoice(Need(kind="metric", term=term, candidates=exact))
    try:
        found = _best(_metric_from_hits(retrieval.metric_terms.get(term, [])))
    except _Tie as tie:
        raise NeedsChoice(Need(kind="metric", term=term, candidates=tie.candidates)) from None
    if found is None or found not in catalog.metrics:
        raise SpecRejected(f"no metric matches '{term}'")
    return found


def _resolve_rank_metric(term: str, catalog: _Catalog, retrieval: Retrieval) -> str:
    exact = catalog.exact_metrics(term)
    if len(exact) == 1:
        return exact[0]
    convention = catalog.convention_metric(term)
    if convention is not None:
        return convention
    candidates = exact or _ranked(_metric_from_hits(retrieval.metric_terms.get(term, [])))
    raise NeedsChoice(Need(kind="metric", term=term, candidates=candidates))


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
        raise NeedsChoice(Need(kind="column", term=term, candidates=[f"{dataset.id}.{column}" for column in exact]))
    try:
        found = _best(_column_from_hits(retrieval.dimension_terms.get(term, []), dataset))
    except _Tie as tie:
        raise NeedsChoice(Need(kind="column", term=term, candidates=[f"{dataset.id}.{c}" for c in tie.candidates])) from None
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


def _value_term_filters(terms: list[GlossaryTerm], dataset: Dataset, filtered: set[str]) -> list[Filter]:
    """Filters for value terms split off metric terms; a column the question already filters is left as asked."""
    by_column: dict[str, list[str]] = {}
    for term in terms:
        targets = [t for t in term.targets if t.dataset == dataset.id and t.column and t.value is not None]
        if not targets:
            raise SpecRejected(f"'{term.term}' names no value of {dataset.id}")
        for target in targets:
            by_column.setdefault(target.column, [])
            if target.value not in by_column[target.column]:
                by_column[target.column].append(target.value)
    return [
        Filter(column=column, op="=", value=values[0]) if len(values) == 1 else Filter(column=column, op="in", value=values)
        for column, values in by_column.items() if column not in filtered
    ]


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


def reviewed_example(state: AgentState, compiled: CompiledPack) -> Hit | None:
    """The first retrieved example asking the question itself with a reviewed spec over known metrics."""
    question = fold(state.get("question", ""))
    metrics = {metric.id for metric in compiled.pack.metrics.metrics}
    for hit in state["retrieval"].examples:
        payload = hit.source.get("payload", {})
        if (
            payload.get("spec") is not None and fold(hit.source.get("title", "")) == question
            and payload.get("metrics") and set(payload["metrics"]) <= metrics and len(payload.get("datasets", [])) == 1
        ):
            return hit
    return None


def _reviewed_spec(state: AgentState, compiled: CompiledPack, example: Hit) -> QuerySpec:
    payload = example.source["payload"]
    reviewed = payload["spec"]
    dataset = {item.id: item for item in compiled.pack.datasets.datasets}[payload["datasets"][0]]
    periods = state["periods"]
    if not periods:
        raise NeedsChoice(Need(kind="period"))
    dimensions = list(reviewed.get("dimensions", []))
    if state.get("time_grain") and dataset.time_column not in dimensions:
        dimensions.append(dataset.time_column)
    filters = [
        Filter(column=item["column"], op=item["op"], value=item["values"] if item["op"] in ("in", "not in") else item["values"][0])
        for item in reviewed.get("filters", [])
    ]
    metric_ids = list(payload["metrics"])
    top_n = reviewed.get("top_n")
    rank_by = reviewed.get("rank_by") or (metric_ids[0] if top_n is not None else None)
    return _finish(state, compiled, metric_ids, dataset, dimensions, filters, top_n, rank_by)


def _finish(state: AgentState, compiled: CompiledPack, metric_ids: list[str], dataset: Dataset, dimensions: list[str],
            filters: list[Filter], top_n: int | None, rank_by: str | None) -> QuerySpec:
    extraction, periods = state["extraction"], state["periods"]
    warnings = []
    compare = extraction.compare and len(periods) > 1
    if extraction.compare and not compare:
        warnings.append("only one period was named, so nothing is compared")
    rank_period = max(periods, key=lambda period: period.start).label if rank_by and len(periods) > 1 else None
    warnings += coverage_warnings(periods, dataset.id, compiled.coverage.get(dataset.id))
    return QuerySpec(
        metric_ids=metric_ids, dimensions=list(dict.fromkeys(dimensions)), periods=periods, filters=filters,
        top_n=top_n, rank_by=rank_by, rank_period=rank_period, compare=compare, dataset=dataset.id,
        warnings=warnings,
    )


def make_spec(state: AgentState, compiled: CompiledPack, example: Hit | None = None) -> QuerySpec:
    """Build the QuerySpec; ``example`` is the approved example whose reviewed spec settles the question."""
    if example is None and state.get("retrieval") is not None:
        example = reviewed_example(state, compiled)
    if example is not None:
        return _reviewed_spec(state, compiled, example)
    extraction = state["extraction"]
    retrieval = state["retrieval"]
    periods = state["periods"]
    catalog = _Catalog(compiled)

    if not extraction.metric_terms and not extraction.rank_term:
        raise NeedsChoice(Need(kind="metric", candidates=_ranked(_metric_from_hits(retrieval.question_metrics))))
    metric_ids = []
    value_terms: list[GlossaryTerm] = []
    for term in extraction.metric_terms:
        words, named = (term, []) if catalog.exact_metrics(term) else catalog.split_values(term)
        metric_ids.append(_resolve_metric(term, catalog, retrieval, words if named else None))
        value_terms += named
    rank_by = None
    if extraction.rank_term:
        try:
            rank_by = _resolve_rank_metric(extraction.rank_term, catalog, retrieval)
        except SpecRejected:
            # A vague ranking word ("top", "cao nhất") next to a named measure ranks by that measure;
            # alone it is still refused rather than guessed.
            if not metric_ids:
                raise
            rank_by = metric_ids[0]
    if rank_by is not None and rank_by not in metric_ids:
        metric_ids.append(rank_by)
    metric_ids = list(dict.fromkeys(metric_ids))
    datasets = {catalog.metrics[metric_id].dataset for metric_id in metric_ids}
    if len(datasets) != 1:
        raise SpecRejected(f"the metrics {', '.join(metric_ids)} come from different datasets")
    dataset = catalog.datasets[datasets.pop()]
    if not periods:
        raise NeedsChoice(Need(kind="period"))

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
    filters += _value_term_filters(value_terms, dataset, {f.column for f in filters})

    if rank_by is None and extraction.top_n is not None:
        rank_by = metric_ids[0]
    return _finish(state, compiled, metric_ids, dataset, dimensions, filters, extraction.top_n, rank_by)


def build_spec(state: AgentState, deps: AgentDeps) -> dict:
    example = reviewed_example(state, deps.compiled)
    try:
        spec = make_spec(state, deps.compiled, example)
    except NeedsChoice as choice:
        return {"need": choice.need}
    except SpecRejected as rejection:
        return {"rejection": str(rejection)}
    except ValidationError as error:
        return {"rejection": f"the question does not form a valid query: {error.errors()[0]['msg']}"}
    update = {"spec": spec, "warnings": [*state.get("warnings", []), *spec.warnings]}
    if example is not None:
        update["spec_example"] = example.id
    return update
