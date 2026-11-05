"""Draft Domain Pack items from a mart profile and document chunks (DECISIONS §11 step 4).

One ``sql-gen`` call per pack file returns items with ``evidence`` and
``confidence``; every item is saved as ``status: draft`` and a person
reviews it before it compiles. The prompts say the profile, the items and
document text are data, never instructions, and that no figures are taken
from text. The code then keeps only evidence that exists in the input (a
profile table or column, or a chunk id), never returns an approved id,
fills an existing draft's text without changing its structure, gives a new
dataset the roles its policies grant, and test-runs every metric expression
and example query: a failure stays a draft with the error as evidence and a
confidence of at most 0.2. Calls are billable.
"""

from collections.abc import Sequence
import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.agent.prompts import render
from app.llm.client import LLMClient
from app.onboarding.pack_yaml import MergeResult, PackFiles
from app.packs.compiler import METRIC_TEST_SETTINGS, CompileError, Warehouse, check_metric_expression, table_ref

TIER = "sql-gen"
DRAFT_FILES = ("datasets.yaml", "glossary.yaml", "metrics.yaml", "examples.yaml")
PROMPTS = {file: f"draft_{file.removesuffix('.yaml')}.v1" for file in DRAFT_FILES}
FAILED_CONFIDENCE = 0.2
ERROR_LIMIT = 300
# Characters of a chunk sent to the drafter.
CHUNK_CHARS = 1500
# Fields an existing draft gets from the drafter; ids, SQL and references stay as reviewed.
FILL_FIELDS = {
    "datasets.yaml": ("description", "grain"),
    "glossary.yaml": ("definition", "aliases"),
    "metrics.yaml": ("name", "description"),
    "examples.yaml": ("question",),
}


class DraftError(RuntimeError):
    """There is nothing to draft from."""


class _Reply(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DraftEvidence(_Reply):
    kind: Literal["profile", "doc"]
    ref: str


class _Drafted(_Reply):
    id: str
    evidence: list[DraftEvidence] = []
    confidence: float = 0.5


class DraftedColumn(_Reply):
    name: str
    type: Literal["string", "number", "date", "datetime", "boolean"]
    role: Literal["dimension", "measure", "time"]
    description: str
    indexable: bool = False


class DraftedDataset(_Drafted):
    description: str
    grain: str
    time_column: str
    columns: list[DraftedColumn]


class DraftedAliases(_Reply):
    vi: list[str] = Field(min_length=1)
    en: list[str] = Field(min_length=1)


class DraftedTarget(_Reply):
    kind: Literal["metric", "column", "value"]
    metric: str | None = None
    dataset: str | None = None
    column: str | None = None
    value: str | None = None


class DraftedTerm(_Drafted):
    term: str
    definition: str
    aliases: DraftedAliases
    targets: list[DraftedTarget] = Field(min_length=1)


class DraftedMetric(_Drafted):
    name: str
    description: str
    dataset: str
    sql_expr: str
    grain: Literal["day", "week", "month", "quarter", "year"]
    unit: Literal["currency", "count", "ratio", "percent", "days", "number"]
    owner: str


class DraftedExample(_Drafted):
    question: str
    language: str
    sql: str
    datasets: list[str] = Field(min_length=1)
    metrics: list[str] = []


class DraftedDatasets(_Reply):
    items: list[DraftedDataset]


class DraftedTerms(_Reply):
    items: list[DraftedTerm]


class DraftedMetrics(_Reply):
    items: list[DraftedMetric]


class DraftedExamples(_Reply):
    items: list[DraftedExample]


REPLIES: dict[str, type[_Reply]] = {
    "datasets.yaml": DraftedDatasets, "glossary.yaml": DraftedTerms,
    "metrics.yaml": DraftedMetrics, "examples.yaml": DraftedExamples,
}


def _first_line(error: BaseException) -> str:
    return (" ".join(str(error).split()) or type(error).__name__)[:ERROR_LIMIT]


def _plain(value):
    """ruamel nodes as plain JSON values."""
    return json.loads(json.dumps(value, default=str))


def profile_refs(profile: dict | None) -> list[str]:
    if not profile:
        return []
    refs: list[str] = []
    for table, facts in profile["tables"].items():
        refs.append(table)
        refs.extend(f"{table}.{column}" for column in facts["columns"])
    return refs


def _granted_roles(files: PackFiles) -> dict[str, list[str]]:
    granted: dict[str, list[str]] = {}
    for role in files.items("policies.yaml"):
        for grant in role.get("datasets") or []:
            granted.setdefault(grant["dataset"], []).append(role["id"])
    return granted


class Drafter:
    def __init__(self, llm: LLMClient, warehouse: Warehouse):
        self.llm = llm
        self.warehouse = warehouse

    def _context(self, file: str, files: PackFiles, profile: dict | None, chunks: Sequence[dict]) -> str:
        items = [_plain(item) for item in files.items(file)]
        context = {
            "profile": profile or {},
            "documents": [{"id": chunk["id"], "source": chunk.get("source", ""), "text": chunk["text"][:CHUNK_CHARS]}
                          for chunk in chunks],
            "approved_ids": [item["id"] for item in items if item.get("status") == "approved"],
            "drafts_to_fill": [item for item in items if item.get("status") != "approved"],
            "datasets": [
                {"id": item["id"], "columns": [column["name"] for column in item.get("columns") or []]}
                for item in _plain(files.items("datasets.yaml"))
            ],
            "metrics": [
                {"id": item["id"], "dataset": item.get("dataset"), "sql_expr": item.get("sql_expr")}
                for item in _plain(files.items("metrics.yaml"))
            ],
        }
        return json.dumps(context, ensure_ascii=False, indent=1)

    def estimate(self, files: PackFiles, profile: dict | None, chunks: Sequence[dict]) -> dict[str, int]:
        """Prompt characters each file's call would send; the job prints it before any billable call."""
        return {
            file: len(render(PROMPTS[file], context=self._context(file, files, profile, chunks)).text)
            for file in DRAFT_FILES
        }

    def draft(self, file: str, files: PackFiles, profile: dict | None, chunks: Sequence[dict]) -> list[dict]:
        """Draft items for ``file``; the result is ready for ``PackFiles.merge_drafts``."""
        if not profile and not chunks:
            raise DraftError("drafting needs a profile or a document to draft from")
        prompt = render(PROMPTS[file], context=self._context(file, files, profile, chunks))
        reply = self.llm.structured(TIER, prompt, REPLIES[file])
        existing = {item["id"]: item for item in files.items(file)}
        refs = {("profile", ref) for ref in profile_refs(profile)} | {("doc", chunk["id"]) for chunk in chunks}
        fallback = (
            {"kind": "profile", "ref": next(iter(profile["tables"]))} if profile and profile["tables"]
            else {"kind": "doc", "ref": chunks[0]["id"]}
        )
        granted = _granted_roles(files)
        drafted: list[dict] = []
        for model in reply.items:
            current = existing.get(model.id)
            if current is not None and current.get("status") == "approved":
                continue
            item = model.model_dump(exclude_none=True)
            evidence = [e for e in item.pop("evidence") if (e["kind"], e["ref"]) in refs] or [fallback]
            item["confidence"] = round(min(max(float(item["confidence"]), 0.0), 1.0), 3)
            if current is not None:
                item = self._fill(file, _plain(current), item)
            elif file == "datasets.yaml":
                item = self._new_dataset(item, granted)
            item["evidence"] = evidence
            item["status"] = "draft"
            self._test_run(file, item)
            drafted.append(item)
        return drafted

    @staticmethod
    def _fill(file: str, current: dict, drafted: dict) -> dict:
        filled = {key: value for key, value in current.items() if key not in ("status", "evidence")}
        for key in FILL_FIELDS[file]:
            if key in drafted:
                filled[key] = drafted[key]
        filled["confidence"] = drafted["confidence"]
        if file == "datasets.yaml":
            descriptions = {column["name"]: column["description"] for column in drafted.get("columns", [])}
            filled["columns"] = [
                {**column, "description": descriptions.get(column["name"], column["description"])}
                for column in current.get("columns") or []
            ]
        return filled

    @staticmethod
    def _new_dataset(item: dict, granted: dict[str, list[str]]) -> dict:
        item["allowed_roles"] = granted.get(item["id"], [])
        item["columns"] = [
            {key: value for key, value in column.items() if key != "indexable" or value} for column in item["columns"]
        ]
        return item

    def _test_run(self, file: str, item: dict) -> None:
        error = None
        if file == "metrics.yaml":
            try:
                check_metric_expression(item["sql_expr"])
                self.warehouse.query(
                    f"SELECT {item['sql_expr']} FROM {table_ref(item['dataset'])} LIMIT 1", settings=METRIC_TEST_SETTINGS
                )
            except (ValueError, CompileError) as failure:
                error = f"sql_expr {failure}"
            except Exception as failure:  # noqa: BLE001 - every driver error is kept as evidence
                error = f"ClickHouse rejected sql_expr: {_first_line(failure)}"
        elif file == "examples.yaml":
            try:
                self.warehouse.query(f"EXPLAIN {item['sql']}", settings=METRIC_TEST_SETTINGS)
            except Exception as failure:  # noqa: BLE001 - every driver error is kept as evidence
                error = f"ClickHouse rejected sql: {_first_line(failure)}"
        if error:
            item["evidence"] = [*item["evidence"], {"kind": "error", "ref": error[:ERROR_LIMIT]}]
            item["confidence"] = min(item["confidence"], FAILED_CONFIDENCE)


def draft_files(
    drafter: Drafter, files: PackFiles, profile: dict | None, chunks: Sequence[dict],
    file_names: Sequence[str] = DRAFT_FILES,
) -> dict[str, MergeResult]:
    """Draft each file in order and save it, so later files see the ids drafted before them."""
    results: dict[str, MergeResult] = {}
    for file in file_names:
        results[file] = files.merge_drafts(file, drafter.draft(file, files, profile, chunks))
        files.save(file)
    return results
