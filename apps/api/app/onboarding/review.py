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
from datetime import UTC, date, datetime
from decimal import Decimal
import json
from pathlib import Path
from typing import Protocol

from app.contracts.result import ColumnInfo, Result
from app.contracts.review import EvidenceRef, ReviewEvidence, ReviewItem
from app.data.clickhouse import QueryLimits
from app.onboarding.documents import DocumentRegistry, is_compiling
from app.onboarding.pack_yaml import ITEM_LISTS, ItemNotFound, PackFiles
from app.onboarding.profiler import base_type
from app.packs.compiler import check_metric_expression, table_ref

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
    ):
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
        return [view for view in views if status is None or view.status == status]

    def items_by_id(self, review_id: str) -> ReviewItem:
        file, item_id = self._split(review_id)
        return self._view(file, _plain(PackFiles(self.pack_dir).find(file, item_id)))

    # changing

    def _guard(self) -> None:
        if is_compiling(self.compiled_dir, self.pack, self.clock()):
            raise ReviewRefused(f"pack {self.pack} is compiling; try again when it finishes", 409)

    def update(self, review_id: str, body: str | None = None, formula: str | None = None) -> ReviewItem:
        self._guard()
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
        file, item_id = self._split(review_id)
        item = _plain(PackFiles(self.pack_dir).find(file, item_id))
        return self._view(file, item, test_result=self._run(file, item))
