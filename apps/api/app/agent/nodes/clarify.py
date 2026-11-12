"""Ask the user what an ambiguous question means (DECISIONS §6 step 8).

``build_spec`` records a ``Need`` when the question names no measure, ranks
by a word no convention defines, uses a term that fits several metrics or
columns equally, or names no period. ``gate`` turns it into a
``Clarification``: a question in the user's language with options that have
stable ids. Choosing an option sends its label as the next question of the
conversation, which ``extract`` reads together with this one. Metric options
are the candidates the asking role may read, at most ``MAX_OPTIONS``, or the
role's readable metrics when no candidate is readable. The question text is
English or Vietnamese; other languages get English.
"""

from collections.abc import Callable
from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.contracts.events import ClarifyOption
from app.packs.models import Pack

MAX_OPTIONS = 4

QUESTIONS = {
    "metric": {"en": "Which measure should I report?", "vi": "Bạn muốn xem chỉ số nào?"},
    "metric_term": {"en": 'Which measure do you mean by "{term}"?', "vi": 'Bạn muốn xem "{term}" theo chỉ số nào?'},
    "column_term": {"en": 'Which column do you mean by "{term}"?', "vi": '"{term}" là cột nào?'},
    "period": {"en": "Which period should I use?", "vi": "Bạn muốn xem khoảng thời gian nào?"},
}
PERIODS = [
    ("this_month", {"en": "This month", "vi": "Tháng này"}),
    ("last_month", {"en": "Last month", "vi": "Tháng trước"}),
    ("this_quarter", {"en": "This quarter", "vi": "Quý này"}),
    ("last_quarter", {"en": "Last quarter", "vi": "Quý trước"}),
    ("this_year", {"en": "This year", "vi": "Năm nay"}),
    ("last_year", {"en": "Last year", "vi": "Năm ngoái"}),
]


class Need(BaseModel):
    """What the question leaves open: a metric or a ``dataset.column``, with its ranked candidates, or a period."""

    model_config = ConfigDict(frozen=True)

    kind: Literal["metric", "column", "period"]
    term: str | None = None
    candidates: list[str] = []


class Clarification(BaseModel):
    model_config = ConfigDict(frozen=True)

    question: str
    options: list[ClarifyOption]
    lang: str


def _text(key: str, language: str, **values: str) -> str:
    templates = QUESTIONS[key]
    return templates.get(language, templates["en"]).format(**values)


def clarification(need: Need, language: str, pack: Pack, may_read: Callable[[str], bool]) -> Clarification:
    """The question for ``need`` in ``language``; ``may_read`` says whether the asking role may read a metric."""
    if need.kind == "period":
        options = [ClarifyOption(id=f"period:{key}", label=labels.get(language, labels["en"])) for key, labels in PERIODS]
        return Clarification(question=_text("period", language), options=options, lang=language)
    if need.kind == "column":
        options = [
            ClarifyOption(id=f"column:{candidate}", label=candidate.split(".", 1)[1]) for candidate in need.candidates[:MAX_OPTIONS]
        ]
        return Clarification(question=_text("column_term", language, term=need.term or ""), options=options, lang=language)
    metrics = {metric.id: metric for metric in pack.metrics.metrics}
    chosen = [metric_id for metric_id in need.candidates if metric_id in metrics and may_read(metric_id)]
    if not chosen:
        chosen = [metric_id for metric_id in metrics if may_read(metric_id)]
    options = [ClarifyOption(id=f"metric:{metric_id}", label=metrics[metric_id].name) for metric_id in chosen[:MAX_OPTIONS]]
    question = _text("metric_term", language, term=need.term) if need.term else _text("metric", language)
    return Clarification(question=question, options=options, lang=language)
