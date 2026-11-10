"""Review drafted pack items before they compile (DECISIONS §11 steps 5-6).

Every reviewable item of the eight pack files is listed as a ``ReviewItem``
whose id is ``<file stem>.<item id>``. A reviewer edits an item's text or
formula (it returns to ``draft``), approves it, deletes it, or test-runs its
formula against ``marts`` as ``pack_review`` with ``readonly=2`` and the
``QUERY_MAX_*`` limits; a metric, example or eval case with a formula is
approved only after a clean test-run. Changes are written to the pack's
working tree and refused while the pack compiles. A document cited as
evidence that was deleted is flagged; the item itself is never changed
automatically.
"""

from collections.abc import Callable, Sequence
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
import json
from pathlib import Path
from typing import Protocol

from app.contracts.result import ColumnInfo, Result
from pydantic import ValidationError

from app.contracts.review import EvidenceRef, ReviewedSpec, ReviewEvidence, ReviewItem
from app.data.clickhouse import QueryLimits
from app.onboarding.documents import DocumentRegistry, is_compiling
from app.onboarding.pack_yaml import ITEM_LISTS, ItemNotFound, PackFiles
from app.onboarding.profiler import base_type
from app.packs.compiler import check_metric_expression, quote, table_ref
from app.feedback.proposals import Proposal

# (name field, body field, formula field) of each file's items.
FIELDS: dict[str, tuple[str, str, str | None]] = {
    "business_profile.yaml": ("id", "description", None),
    "datasets.yaml": ("id", "description", None),
    "glossary.yaml": ("term", "definition", None),
    "metrics.yaml": ("id", "description", "sql_expr"),
    "relationships.yaml": ("id", "description", None),
    "examples.yaml": ("id", "question", "sql"),
    "policies.yaml": ("id", "description", None),
    "eval.yaml": ("id", "question", "expected_sql"),
}
TEST_ROWS = 100
PROPOSALS = "proposals"
MASK = "[MASKED_"
_VIETNAMESE = set("ăâđêôơưàáảãạằắẳẵặầấẩẫậèéẻẽẹềếểễệìíỉĩịòóỏõọồốổỗộờớởỡợùúủũụừứửữựỳýỷỹỵ")
ERROR_LIMIT = 500


class ReviewRefused(Exception):
    """The change cannot be made; ``status`` is the HTTP status the api answers."""

    def __init__(self, message: str, status: int = 422):
        super().__init__(message)
        self.status = status


class TableWarehouse(Protocol):
    def query_table(self, sql: str, settings: dict | None = None) -> tuple[Sequence[str], Sequence[str], Sequence[Sequence]]:
        """Run one SELECT and return its column names, ClickHouse types and rows."""


def _plain(value):
    return json.loads(json.dumps(value, default=str))


def _cell(value):
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    return str(value)


def _first_line(error: BaseException) -> str:
    return (" ".join(str(error).split()) or type(error).__name__)[:ERROR_LIMIT]


class ReviewService:
    def __init__(
        self,
        *,
        pack: str,
        pack_dir: Path,
        registry: DocumentRegistry,
        warehouse: TableWarehouse,
        limits: QueryLimits,
        compiled_dir: Path,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        proposals=None,
    ):
        """``proposals`` is the example proposal store; without it the Review page lists pack items only."""
        self.proposals = proposals
        self.pack = pack
        self.pack_dir = pack_dir
        self.registry = registry
        self.warehouse = warehouse
        self.limits = limits
        self.compiled_dir = compiled_dir
        self.clock = clock

    # reading

    @staticmethod
    def _split(review_id: str) -> tuple[str, str]:
        stem, _, item_id = review_id.partition(".")
        file = f"{stem}.yaml"
        if file not in ITEM_LISTS or not item_id:
            raise ItemNotFound(f"no review item {review_id!r}")
        return file, item_id

    def _evidence(self, refs: list[dict]) -> ReviewEvidence | None:
        if not refs:
            return None
        cited = [ref for ref in refs if ref["kind"] == "doc"]
        if cited:
            deleted = False
            names = []
            for ref in cited:
                record = self.registry.get(self.pack, ref["ref"].split("#", 1)[0])
                deleted = deleted or record is None or record.deleted_at is not None
                names.append(record.file_name if record else ref["ref"])
            return ReviewEvidence(source=", ".join(dict.fromkeys(names)), deleted=deleted)
        first = refs[0]
        if first["kind"] == "profile":
            return ReviewEvidence(source=f"Profile of {first['ref']}")
        if first["kind"] == "error":
            return ReviewEvidence(source="Test-run error", quote=first["ref"])
        if first["kind"] == "trace":
            return ReviewEvidence(source=f"Trace {first['ref']}")
        return ReviewEvidence(source=first["ref"])

    def _view(self, file: str, item: dict, test_result: Result | None = None) -> ReviewItem:
        name_field, body_field, formula_field = FIELDS[file]
        refs = item.get("evidence") or []
        return ReviewItem(
            id=f"{file.removesuffix('.yaml')}.{item['id']}", file=file, name=str(item.get(name_field) or item["id"]),
            kind="item", status=item.get("status", "draft"), confidence=float(item.get("confidence", 0)),
            body=str(item.get(body_field) or ""),
            formula=item.get(formula_field) if formula_field else None,
            evidence=self._evidence(refs), evidence_refs=[EvidenceRef(**ref) for ref in refs],
            test_result=test_result,
        )

    def items(self, file: str | None = None, status: str | None = None) -> list[ReviewItem]:
        files = PackFiles(self.pack_dir)
        names = [file] if file else list(ITEM_LISTS)
        views = []
        for name in names:
            if name not in ITEM_LISTS:
                raise ItemNotFound(f"{name} is not a pack file")
            views.extend(self._view(name, _plain(item)) for item in files.items(name))
        if self.proposals is not None and file in (None, "examples.yaml"):
            views.extend(self._proposal_view(proposal) for proposal in self.proposals.proposals(self.pack))
        return [view for view in views if status is None or view.status == status]

    # proposals

    def _proposal_spec(self, proposal: Proposal) -> tuple[ReviewedSpec | None, bool]:
        """The proposal's spec as the reviewer edits it, and whether the reviewer has confirmed it.

        Until edited it is the run's QuerySpec without the time column (the question's time grain adds it back)
        and with each filter's values as a list; filter values stay masked as redaction left them.
        """
        data = json.loads(proposal.spec or "{}")
        datasets = {item.get("id"): item for item in PackFiles(self.pack_dir).items("datasets.yaml")}
        time_column = datasets.get(data.get("dataset"), {}).get("time_column")
        filters = []
        for item in data.get("filters") or []:
            values = item["values"] if "values" in item else item.get("value")
            filters.append({"column": item.get("column"), "op": item.get("op"), "values": values if isinstance(values, list) else [values]})
        try:
            spec = ReviewedSpec(
                metric_ids=data.get("metric_ids") or [], dataset=data.get("dataset") or "",
                dimensions=[column for column in data.get("dimensions") or [] if column != time_column],
                filters=filters, top_n=data.get("top_n"), rank_by=data.get("rank_by"),
            )
        except ValidationError:
            return None, False
        return spec, data.get("reviewed") is True

    def _proposal_view(self, proposal: Proposal, test_result: Result | None = None) -> ReviewItem:
        spec, reviewed = self._proposal_spec(proposal)
        return ReviewItem(
            id=f"{PROPOSALS}.{proposal.proposal_id}", file="examples.yaml", name=proposal.question[:80],
            kind="proposal", status="draft", confidence=proposal.confidence, body=proposal.question,
            formula=proposal.sql,
            evidence=ReviewEvidence(source=f"Trace {proposal.trace_id}", quote=proposal.note or proposal.error or None),
            evidence_refs=[EvidenceRef(kind="trace", ref=proposal.trace_id)], test_result=test_result,
            spec=spec, spec_reviewed=reviewed,
        )

    def _proposal(self, proposal_id: str) -> Proposal:
        if self.proposals is None:
            raise ItemNotFound(f"no review item proposals.{proposal_id}")
        for proposal in self.proposals.proposals(self.pack):
            if proposal.proposal_id == proposal_id:
                return proposal
        raise ItemNotFound(f"no open proposal {proposal_id}")

    def _save_proposal(self, proposal: Proposal, **changes) -> Proposal:
        updated = replace(proposal, ts=max(self.clock(), proposal.ts + timedelta(milliseconds=1)), **changes)
        self.proposals.save(updated)
        return updated

    def _approve_proposal(self, proposal: Proposal) -> ReviewItem:
        if MASK in proposal.question or MASK in proposal.sql:
            raise ReviewRefused("replace every masked value with a valid non-personal value before approving")
        try:
            self._run("examples.yaml", {"id": proposal.proposal_id, "sql": proposal.sql})
        except ReviewRefused as error:
            raise ReviewRefused(f"approve after a clean test-run; the test-run failed: {error}") from None
        spec = json.loads(proposal.spec or "{}")
        reviewed, confirmed = self._proposal_spec(proposal)
        if confirmed:
            self._check_spec(reviewed)
        language = "vi" if set(proposal.question.lower()) & _VIETNAMESE else "en"
        example = {
            "id": f"proposal_{proposal.proposal_id[:12]}", "question": proposal.question, "language": language,
            "sql": proposal.sql, "datasets": [spec["dataset"]] if spec.get("dataset") else [],
            "metrics": list(spec.get("metric_ids") or []), "status": "approved",
            "evidence": [{"kind": "trace", "ref": proposal.trace_id}], "confidence": proposal.confidence,
        }
        if confirmed:
            example["spec"] = {
                "dimensions": reviewed.dimensions,
                "filters": [item.model_dump(mode="json") for item in reviewed.filters],
                **({"top_n": reviewed.top_n} if reviewed.top_n is not None else {}),
                **({"rank_by": reviewed.rank_by} if reviewed.rank_by is not None else {}),
            }
        files = PackFiles(self.pack_dir)
        files.items("examples.yaml").append(example)
        files._changed.add("examples.yaml")  # noqa: SLF001 - an approved example is appended as reviewed
        files.save("examples.yaml")
        self._save_proposal(proposal, status="approved")
        return self._view("examples.yaml", example)

    def _check_spec(self, spec: ReviewedSpec) -> None:
        """Refuse a reviewed spec that names an unknown or mismatched pack item, a masked value or a value not in the data."""
        files = PackFiles(self.pack_dir)
        datasets = {item.get("id"): item for item in files.items("datasets.yaml")}
        metrics = {item.get("id"): item for item in files.items("metrics.yaml")}
        if spec.dataset not in datasets:
            raise ReviewRefused(f"unknown dataset '{spec.dataset}'")
        for metric_id in spec.metric_ids:
            if metric_id not in metrics:
                raise ReviewRefused(f"unknown metric '{metric_id}'")
            if metrics[metric_id].get("dataset") != spec.dataset:
                raise ReviewRefused(
                    f"metric '{metric_id}' is computed from dataset '{metrics[metric_id].get('dataset')}', not '{spec.dataset}'")
        columns = {column.get("name") for column in datasets[spec.dataset].get("columns", [])}
        for column in [*spec.dimensions, *(item.column for item in spec.filters)]:
            if column not in columns:
                raise ReviewRefused(f"unknown column '{column}' in dataset '{spec.dataset}'")
        if spec.rank_by is not None and spec.rank_by not in spec.metric_ids:
            raise ReviewRefused("rank_by must be one of the spec's metrics")
        for item in spec.filters:
            if item.op in ("=", "!=") and len(item.values) != 1:
                raise ReviewRefused(f"operator '{item.op}' takes exactly one value")
            if any(isinstance(value, str) and MASK in value for value in item.values):
                raise ReviewRefused("replace every masked value in the spec's filters with a value from the data")
        for item in spec.filters:
            for value in item.values:
                literal = "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'" if isinstance(value, str) else repr(value)
                sql = f"SELECT 1 FROM {table_ref(spec.dataset)} WHERE {quote(item.column)} = {literal} LIMIT 1"
                try:
                    _, _, rows = self.warehouse.query_table(sql, settings=self._settings())
                except Exception as error:  # noqa: BLE001 - the reviewer sees ClickHouse's message
                    raise ReviewRefused(f"ClickHouse rejected the value check: {_first_line(error)}") from None
                if not rows:
                    raise ReviewRefused(f"'{value}' is not a value of {spec.dataset}.{item.column}")

    def items_by_id(self, review_id: str) -> ReviewItem:
        if review_id.startswith(f"{PROPOSALS}."):
            return self._proposal_view(self._proposal(review_id.split(".", 1)[1]))
        file, item_id = self._split(review_id)
        return self._view(file, _plain(PackFiles(self.pack_dir).find(file, item_id)))

    # changing

    def _guard(self) -> None:
        if is_compiling(self.compiled_dir, self.pack, self.clock()):
            raise ReviewRefused(f"pack {self.pack} is compiling; try again when it finishes", 409)

    def update(self, review_id: str, body: str | None = None, formula: str | None = None,
               spec: ReviewedSpec | None = None, spec_reviewed: bool | None = None) -> ReviewItem:
        self._guard()
        if review_id.startswith(f"{PROPOSALS}."):
            proposal = self._proposal(review_id.split(".", 1)[1])
            changes = {key: value for key, value in (("question", body), ("sql", formula)) if value is not None}
            if spec is not None:
                changes["spec"] = json.dumps({**spec.model_dump(mode="json"), "reviewed": spec_reviewed is not False})
            elif spec_reviewed is not None:
                changes["spec"] = json.dumps({**json.loads(proposal.spec or "{}"), "reviewed": spec_reviewed})
            return self._proposal_view(self._save_proposal(proposal, **changes))
        if spec is not None or spec_reviewed is not None:
            raise ReviewRefused("only a proposal has a spec")
        file, item_id = self._split(review_id)
        _, body_field, formula_field = FIELDS[file]
        fields: dict = {}
        if body is not None:
            fields[body_field] = body
        if formula is not None:
            if formula_field is None:
                raise ReviewRefused(f"a {file} item has no formula")
            fields[formula_field] = formula
        files = PackFiles(self.pack_dir)
        item = files.update(file, item_id, fields)
        files.save(file)
        return self._view(file, _plain(item))

    def approve(self, review_id: str) -> ReviewItem:
        self._guard()
        if review_id.startswith(f"{PROPOSALS}."):
            return self._approve_proposal(self._proposal(review_id.split(".", 1)[1]))
        file, item_id = self._split(review_id)
        files = PackFiles(self.pack_dir)
        item = _plain(files.find(file, item_id))
        if FIELDS[file][2] and item.get(FIELDS[file][2]):
            try:
                self._run(file, item)
            except ReviewRefused as error:
                raise ReviewRefused(f"approve after a clean test-run; the test-run failed: {error}") from None
        approved = files.approve(file, item_id)
        files.save(file)
        return self._view(file, _plain(approved))

    def delete(self, review_id: str) -> None:
        self._guard()
        if review_id.startswith(f"{PROPOSALS}."):
            self._save_proposal(self._proposal(review_id.split(".", 1)[1]), status="dismissed")
            return
        file, item_id = self._split(review_id)
        files = PackFiles(self.pack_dir)
        files.delete(file, item_id)
        files.save(file)

    # test-run

    def _settings(self) -> dict:
        return {
            "readonly": 2, "max_execution_time": self.limits.max_execution_time,
            "max_memory_usage": self.limits.max_memory_usage, "max_result_rows": TEST_ROWS,
            "result_overflow_mode": "break",
        }

    def _run(self, file: str, item: dict) -> Result:
        formula = item.get(FIELDS[file][2] or "")
        if not formula:
            raise ReviewRefused(f"{file} item {item['id']} has nothing to test-run")
        if file == "metrics.yaml":
            try:
                check_metric_expression(formula)
            except ValueError as error:
                raise ReviewRefused(f"sql_expr {error}") from None
            sql = f"SELECT {formula} AS value FROM {table_ref(item['dataset'])} LIMIT 1"
        else:
            sql = formula
        try:
            names, types, rows = self.warehouse.query_table(sql, settings=self._settings())
        except Exception as error:  # noqa: BLE001 - the reviewer sees ClickHouse's message
            raise ReviewRefused(f"ClickHouse rejected the query: {_first_line(error)}") from None
        columns = []
        for name, clickhouse_type in zip(names, types, strict=True):
            kind = base_type(clickhouse_type)
            kind = kind if kind != "other" else "string"
            role = "measure" if kind == "number" else "time" if kind in ("date", "datetime") else "dimension"
            columns.append(ColumnInfo(name=name, type=kind, role=role))
        cells = [[_cell(value) for value in row] for row in rows[:TEST_ROWS]]
        return Result(columns=columns, rows=cells, row_count=len(cells))

    def test_run(self, review_id: str) -> ReviewItem:
        if review_id.startswith(f"{PROPOSALS}."):
            proposal = self._proposal(review_id.split(".", 1)[1])
            result = self._run("examples.yaml", {"id": proposal.proposal_id, "sql": proposal.sql})
            return self._proposal_view(proposal, test_result=result)
        file, item_id = self._split(review_id)
        item = _plain(PackFiles(self.pack_dir).find(file, item_id))
        return self._view(file, item, test_result=self._run(file, item))
