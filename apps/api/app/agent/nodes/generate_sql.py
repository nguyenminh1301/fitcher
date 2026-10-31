"""Generate SQL for the QuerySpec (DECISIONS §6 step 9).

The prompt carries the spec, the permitted schema of the spec's dataset and
the datasets joined to it, the metric expressions, the declared joins, the
retrieved examples and, on a retry, the previous SQL and its error. One
initial generation and up to three retries run in total; the third retry uses
``sql-gen-hard`` (DECISIONS §2 and §6).
"""

import json
import re

from app.agent.errors import AgentError
from app.agent.prompts import render
from app.agent.state import AgentDeps, AgentState, Attempt
from app.llm.client import LLMError
from app.packs.models import Pack

PROMPT = "generate_sql.v1"
MAX_GENERATIONS = 4
EXAMPLES_IN_PROMPT = 3
_FENCE = re.compile(r"^```[a-zA-Z]*\s*|\s*```$")


def alias_for(attempt: int) -> str:
    """LLM alias for the zero-based generation ``attempt``."""
    return "sql-gen-hard" if attempt >= MAX_GENERATIONS - 1 else "sql-gen"


def _related_datasets(pack: Pack, dataset: str) -> list[str]:
    related = [dataset]
    for relationship in pack.relationships.relationships:
        if dataset in (relationship.from_dataset, relationship.to_dataset):
            related.extend([relationship.from_dataset, relationship.to_dataset])
    return list(dict.fromkeys(related))


def _schema(pack: Pack, datasets: list[str]) -> str:
    blocks = []
    for dataset in pack.datasets.datasets:
        if dataset.id not in datasets:
            continue
        lines = [f"marts.{dataset.id}: {dataset.description} Grain: {dataset.grain}. Time column: {dataset.time_column}."]
        lines += [f"  - {column.name} ({column.type}, {column.role}): {column.description}" for column in dataset.columns]
        blocks.append("\n".join(lines))
    return "\n".join(blocks)


def _joins(pack: Pack, datasets: list[str]) -> str:
    lines = [
        f"- marts.{r.from_dataset} JOIN marts.{r.to_dataset} ON "
        + " AND ".join(f"{r.from_dataset}.{pair.from_column} = {r.to_dataset}.{pair.to_column}" for pair in r.on)
        + f" ({r.cardinality})"
        for r in pack.relationships.relationships
        if r.from_dataset in datasets and r.to_dataset in datasets
    ]
    return "\n".join(lines) or "none"


def build_prompt(state: AgentState, deps: AgentDeps) -> str:
    pack = deps.compiled.pack
    spec = state["spec"]
    datasets = _related_datasets(pack, spec.dataset)
    metrics = {metric.id: metric for metric in pack.metrics.metrics}
    examples = [
        f"Question: {hit.source['title']}\nSQL:\n{hit.source['payload']['sql']}"
        for hit in state["retrieval"].examples[:EXAMPLES_IN_PROMPT]
    ]
    retry = ""
    attempts = state.get("attempts", [])
    if attempts and attempts[-1].error is not None:
        retry = (
            "\nThe previous attempt failed. Fix the query.\nPrevious SQL:\n"
            f"{attempts[-1].sql}\nError:\n{attempts[-1].error.message}\n"
        )
    return render(
        PROMPT,
        spec=json.dumps(spec.model_dump(mode="json", exclude={"warnings"}), ensure_ascii=False, indent=2),
        time_grain=state.get("time_grain") or "none",
        schema=_schema(pack, datasets),
        metrics="\n".join(
            f"- {metric_id} ({metrics[metric_id].unit}): {metrics[metric_id].sql_expr}" for metric_id in spec.metric_ids
        ),
        joins=_joins(pack, datasets),
        examples="\n\n".join(examples) or "none",
        retry=retry,
    )


def clean_sql(reply: str) -> str:
    return _FENCE.sub("", reply.strip()).strip()


def generate_sql(state: AgentState, deps: AgentDeps) -> dict:
    attempts = list(state.get("attempts", []))
    alias = alias_for(len(attempts))
    try:
        sql = clean_sql(deps.llm.text(alias, build_prompt(state, deps)))
    except LLMError as error:
        failed = AgentError("runtime", "generate_sql", str(error))
        return {
            "attempts": [*attempts, Attempt(alias=alias, sql="", error=failed)],
            "errors": [*state.get("errors", []), failed], "sql": None, "output": None,
        }
    return {"attempts": [*attempts, Attempt(alias=alias, sql=sql)], "sql": sql, "output": None}
