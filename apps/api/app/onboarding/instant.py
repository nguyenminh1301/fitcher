"""The instant pack: from a connected source's chosen tables to a pack that answers (DECISIONS §11 step 0).

One job runs the steps in ``STEPS``: build the mart views as ``pack_admin``, profile them, write the deterministic
pack files, let the drafter fill them (the one billable step, sent only with an explicit confirmation), approve the
generated items as unreviewed, compile the pack and make it the active pack. The pack is named after the source.

The files are built in ``<packs dir>/<pack>.building`` and replace the pack's directory only for the compile,
which publishes the search indices and ``compiled.json`` atomically at its end. A failure at any step therefore
leaves the previous pack live: its directory is put back, its compiled pack is untouched, and the views of tables
no longer chosen are dropped only after the new pack is active. The job records which step failed and why.

Jobs live in the api process; one runs at a time.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
import logging
import re
import secrets
import shutil
import tempfile
import threading
from pathlib import Path

from app.observability.tracing import trusted_pack_calls
from app.onboarding.drafter import DRAFT_FILES, pack_id
from app.onboarding.drift import write_snapshot
from app.onboarding.instant_files import approve_generated, write_pack_files
from app.onboarding.marts import (
    MARTS_DATABASE, MartTable, MartView, SourceColumn, mart_tables, plan_marts, source_marts,
)
from app.onboarding.pack_yaml import ITEM_LISTS, PackFiles
from app.onboarding.profiler import profile_marts
from app.packs.loader import file_issues
from app.sources.attach import quote
from app.sources.inspect import classify_error

logger = logging.getLogger(__name__)
STEPS = ("marts", "profile", "files", "draft", "approve", "compile", "activate")
CHARS_PER_TOKEN = 4
SUGGESTED_QUESTIONS = 3
BUILDING_SUFFIX = ".building"
PREVIOUS_SUFFIX = ".previous"
ERROR_LIMIT = 300


class InstantRefused(ValueError):
    """The request cannot start a job; ``status`` is the HTTP status the api answers."""

    def __init__(self, message: str, status: int = 422):
        super().__init__(message)
        self.status = status


@dataclass
class InstantJob:
    id: str
    source_id: str
    tables: list[str]
    started_by: str
    started_at: str
    status: str = "running"
    steps: list[dict] = field(default_factory=lambda: [{"id": step, "state": "pending"} for step in STEPS])
    failed_step: str | None = None
    error: str | None = None
    # When ClickHouse refused a step, one reason of ``app.sources.inspect.REASONS``: the interface words it, and
    # ``error`` holds a plain sentence instead of ClickHouse's text, which can quote data values.
    error_reason: str | None = None
    # Whether the source had a pack before this build, which a failed build leaves answering.
    had_pack: bool = False
    result: dict | None = None
    finished_at: str | None = None

    def _set(self, step: str, state: str) -> None:
        next(item for item in self.steps if item["id"] == step)["state"] = state

    def _progress(self, step: str, phase: str, done: int, total: int) -> None:
        """How much of a long step is done: the compile reports the values screened, then the texts embedded."""
        next(item for item in self.steps if item["id"] == step).update(phase=phase, done=done, total=total)


class InstantWarehouse:
    """A clickhouse-connect client as the profiler's and compiler's ``Warehouse`` and ``AccessControl``."""

    def __init__(self, client):
        self._client = client

    def query(self, sql: str, settings: dict | None = None):
        return self._client.query(sql, settings=settings).result_rows

    def command(self, sql: str) -> None:
        self._client.command(sql)


def wide_profiles(views: Sequence[MartView], profile: dict) -> dict:
    """``profile`` of the views' own tables with the wide views added, derived from the tables they join.

    A wide view holds its table's rows and columns and, for each joined column, the referenced table's values, so its
    facts are those of its tables and scanning the join, which can exceed the query memory limit, is not needed.
    The sample rows are left out: they would need the join.
    """
    tables = dict(profile["tables"])
    for view in views:
        if not view.wide:
            continue
        own = tables[view.origins[0][1]]
        tables[view.name] = {
            "rows": own["rows"],
            "columns": {output: tables[mart]["columns"][column] for output, mart, column in view.origins},
            "sample_rows": [],
        }
    return {**profile, "tables": tables}


# Drafted files whose rejected items are dropped; a dataset describes a mart that exists, so it is never dropped.
DROPPABLE_FILES = ("glossary.yaml", "metrics.yaml", "examples.yaml")


def drop_invalid_drafts(files: PackFiles, file: str) -> list[str]:
    """Remove the drafted items of ``file`` that its schema rejects, and name them as ``<file>.<id>``.

    A model can return an item that parses but breaks the pack schema (a glossary target of kind ``metric``
    without its metric); without this one such item would fail the whole pack. Only drafts are removed: an
    item that was approved before keeps failing loudly, and so does a dataset, whose mart already exists.
    """
    if file not in DROPPABLE_FILES:
        return []
    [key] = ITEM_LISTS[file]
    dropped: list[str] = []
    while True:
        issues = file_issues(file, files.text(file), files.schema_dir)
        items = files.items(file)
        positions = sorted({int(match.group(1)) for issue in issues
                            if (match := re.match(rf"{re.escape(key)}\[(\d+)\]", issue.path))}, reverse=True)
        broken = [index for index in positions if index < len(items) and items[index].get("status") == "draft"]
        if not broken:
            return dropped
        for index in broken:
            dropped.append(f"{file.removesuffix('.yaml')}.{items[index].get('id')}")
            del items[index]


def fallback_metrics(datasets: Sequence[dict]) -> list[dict]:
    """The metrics of a pack whose draft returned none: each dataset's row count and the total of each measure."""
    metrics = []
    for dataset in datasets:
        base = {"dataset": dataset["id"], "grain": "day", "owner": "instant pack", "confidence": 0.3, "status": "draft",
                "evidence": [{"kind": "profile", "ref": dataset["id"]}]}
        metrics.append({**base, "id": pack_id(f"{dataset['id']}_rows"), "name": f"Rows of {dataset['id']}",
                        "description": f"The number of rows of {dataset['id']}.", "sql_expr": "count()", "unit": "count"})
        for column in dataset.get("columns") or []:
            if column.get("role") == "measure":
                plain = column["name"].isidentifier() and column["name"].isascii()
                metrics.append({**base, "id": pack_id(f"{dataset['id']}_{column['name']}_total"),
                                "name": f"Total {column['name']} of {dataset['id']}",
                                "description": f"The sum of {column['name']} over the rows of {dataset['id']}.",
                                "sql_expr": f"sum({column['name'] if plain else quote(column['name'])})", "unit": "number"})
    return metrics


# Plain sentences for a step ClickHouse refused, by reason; the interface shows its own translation of the reason.
CLICKHOUSE_REASONS = {
    "value_out_of_range": "a value of the data does not fit the column type ClickHouse reads it as",
    "unsupported_name": "ClickHouse cannot read a table of the source by its name",
    "empty_or_unreadable": "a table has no rows or ClickHouse cannot read its format",
    "unreachable": "the source could not be reached",
    "refused": "the source refused the connection",
    "authentication": "the source refused the user or password",
    "tls": "the TLS settings do not match the source",
    "database_not_found": "the source's database was not found",
    "permission": "the source's user may not read a table",
    "unknown": "ClickHouse refused a query of this step",
}
_CLICKHOUSE_TEXT = re.compile(r"DB::Exception|\bCode: \d+\.")


def _from_clickhouse(error: BaseException) -> bool:
    return bool(_CLICKHOUSE_TEXT.search(str(error)))


def _first_line(error: BaseException) -> str:
    return (" ".join(str(error).split()) or type(error).__name__)[:ERROR_LIMIT]


class InstantPipeline:
    def __init__(self, *, store, client, packs_dir: Path, schema_dir: Path, drafter: Callable[[], object],
                 compile_pack: Callable[..., object], activate: Callable[[str], None],
                 model_missing: Callable[[], str | None], clock: Callable[[], datetime] = lambda: datetime.now(UTC)):
        """``drafter`` builds the drafter when the draft step starts; ``model_missing`` says why no model can draft."""
        self._store = store
        self._client = client
        self._packs_dir = Path(packs_dir)
        self._schema_dir = Path(schema_dir)
        self._drafter = drafter
        self._compile_pack = compile_pack
        self._activate_pack = activate
        self._model_missing = model_missing
        self._clock = clock
        self._jobs: dict[str, InstantJob] = {}
        self._lock = threading.Lock()

    # requests

    def _chosen(self, source_id: str, tables: Sequence[str]):
        if not tables:
            raise InstantRefused("choose at least one table")
        known = {table.name: table for table in self._store.tables(source_id)}
        unknown = [name for name in tables if name not in known]
        if unknown:
            raise InstantRefused(f"unknown table {', '.join(unknown)} in source {source_id}")
        return [known[name] for name in tables]

    def estimate(self, source_id: str, tables: Sequence[str]) -> dict:
        """Prompt tokens of the draft, from the source's catalog alone: nothing is read from the data."""
        chosen = self._chosen(source_id, tables)
        catalog = [MartTable(name=table.name, relation=table.name, live=table.mode == "live",
                             columns=tuple(SourceColumn(column.name, "String") for column in table.columns),
                             primary_key=tuple(table.primary_key), foreign_keys=tuple(table.foreign_keys))
                   for table in chosen]
        views = plan_marts(source_id, catalog)
        profile = {"tables": {view.name: {"rows": 0, "columns": {name: {"type": "string", "distinct": 0}
                                                                 for name in view.columns}} for view in views},
                   "join_candidates": []}
        with tempfile.TemporaryDirectory() as empty:
            files = PackFiles(Path(empty), schema_dir=self._schema_dir)
            characters = sum(self._drafter().estimate(files, profile, []).values())
        return {"prompt_tokens": characters // CHARS_PER_TOKEN, "datasets": len(views), "model_missing": self._model_missing()}

    def new_job(self, source_id: str, tables: Sequence[str], started_by: str) -> InstantJob:
        self._chosen(source_id, tables)
        with self._lock:
            if any(job.status == "running" for job in self._jobs.values()):
                raise InstantRefused("an instant pack is already being built; wait for it to finish", 409)
            job = InstantJob(id=secrets.token_hex(8), source_id=source_id, tables=list(tables), started_by=started_by,
                             started_at=self._clock().isoformat(), had_pack=(self._packs_dir / source_id).is_dir())
            self._jobs[job.id] = job
        return job

    def start(self, source_id: str, tables: Sequence[str], *, confirm_billable: bool, started_by: str) -> InstantJob:
        """Start a job on a thread; the draft is billable, so the request must confirm it."""
        if not confirm_billable:
            raise InstantRefused("drafting the pack is a billable model call: confirm it to start")
        job = self.new_job(source_id, tables, started_by)
        threading.Thread(target=self.run, args=(job,), name=f"instant-{source_id}", daemon=True).start()
        return job

    def job(self, job_id: str) -> InstantJob | None:
        return self._jobs.get(job_id)

    def latest_job(self, source_id: str) -> InstantJob | None:
        """The source's most recent pack build of this process, running or finished."""
        jobs = [job for job in self._jobs.values() if job.source_id == source_id]
        return max(jobs, key=lambda job: job.started_at) if jobs else None

    # the job

    def run(self, job: InstantJob) -> InstantJob:
        pack = job.source_id
        building = self._packs_dir / f"{pack}{BUILDING_SUFFIX}"
        state: dict = {}
        current = STEPS[0]
        try:
            # The drafter reads the pack's own profile and the compile embeds the pack's content, as the jobs do;
            # the compile screens column values itself (DECISIONS §9).
            with trusted_pack_calls():
                for current in STEPS:
                    job._set(current, "running")
                    getattr(self, f"_step_{current}")(job, pack, building, state)
                    job._set(current, "done")
        except Exception as error:  # noqa: BLE001 - the job reports the step and the reason
            job._set(current, "failed")
            job.status, job.failed_step = "failed", current
            job.error = state.get("missing") or _first_line(error)
            if not state.get("missing") and _from_clickhouse(error):
                # The full text stays in the log for the console; the job carries the reason only.
                logger.warning("instant pack %s failed at step %s: %s", pack, current, job.error)
                job.error_reason = classify_error(error)
                job.error = CLICKHOUSE_REASONS.get(job.error_reason, CLICKHOUSE_REASONS["unknown"])
            self._restore(pack, state)
        else:
            job.status = "succeeded"
        finally:
            shutil.rmtree(building, ignore_errors=True)
            job.finished_at = self._clock().isoformat()
        return job

    def _step_marts(self, job: InstantJob, pack: str, building: Path, state: dict) -> None:
        source = self._store.get(job.source_id)
        tables = mart_tables(self._client, job.source_id, source.kind, self._chosen(job.source_id, job.tables))
        views = plan_marts(job.source_id, tables)
        state["stale"] = [name for name in source_marts(self._client, job.source_id)
                          if name not in {view.name for view in views}]
        for view in views:
            self._client.command(view.statement())
        state["tables"], state["views"] = tables, views

    def _step_profile(self, job: InstantJob, pack: str, building: Path, state: dict) -> None:
        bases = [view.name for view in state["views"] if not view.wide]
        state["profile"] = wide_profiles(state["views"], profile_marts(InstantWarehouse(self._client), bases))

    def _step_files(self, job: InstantJob, pack: str, building: Path, state: dict) -> None:
        shutil.rmtree(building, ignore_errors=True)
        state["summary"] = write_pack_files(
            building, pack=pack, display_name=pack.replace("_", " ").capitalize(), source=job.source_id,
            tables=state["tables"], views=state["views"], profile=state["profile"])
        write_snapshot(building, job.source_id, self._chosen(job.source_id, job.tables))

    def _step_draft(self, job: InstantJob, pack: str, building: Path, state: dict) -> None:
        missing = self._model_missing()
        if missing:
            state["missing"] = missing
            raise RuntimeError(missing)
        drafter = self._drafter()
        files = PackFiles(building, schema_dir=self._schema_dir)
        for file in DRAFT_FILES:
            files.merge_drafts(file, drafter.draft(file, files, state["profile"], []))
            if file == "metrics.yaml" and not files.items(file):
                # A model sometimes returns no metric at all, and a pack without metrics answers no question
                # about amounts: it is asked once more, then the pack gets row counts and column totals.
                files.merge_drafts(file, drafter.draft(file, files, state["profile"], []))
                if not files.items(file):
                    files.merge_drafts(file, fallback_metrics(files.items("datasets.yaml")))
            state.setdefault("invalid", []).extend(drop_invalid_drafts(files, file))
            files.save(file)

    def _step_approve(self, job: InstantJob, pack: str, building: Path, state: dict) -> None:
        state["dropped"] = [*state.get("invalid", []), *approve_generated(building, schema_dir=self._schema_dir)["dropped"]]

    def _step_compile(self, job: InstantJob, pack: str, building: Path, state: dict) -> None:
        target = self._packs_dir / pack
        previous = self._packs_dir / f"{pack}{PREVIOUS_SUFFIX}"
        shutil.rmtree(previous, ignore_errors=True)
        if target.exists():
            target.rename(previous)
            state["previous"] = previous
        building.rename(target)
        state["swapped"] = True
        self._compile_pack(target, progress=lambda phase, done, total: job._progress("compile", phase, done, total))

    def _step_activate(self, job: InstantJob, pack: str, building: Path, state: dict) -> None:
        self._activate_pack(pack)
        for name in state.get("stale", []):
            self._client.command(f"DROP VIEW IF EXISTS {quote(MARTS_DATABASE)}.{quote(name)}")
        shutil.rmtree(state.get("previous") or self._packs_dir / f"{pack}{PREVIOUS_SUFFIX}", ignore_errors=True)
        examples = [item for item in PackFiles(self._packs_dir / pack, schema_dir=self._schema_dir).items("examples.yaml")
                    if item.get("status") == "approved"]
        job.result = {
            "pack": pack, **state["summary"], "dropped": state.get("dropped", []),
            "slow": [view.name for view in state["views"] if view.slow],
            "unreadable_columns": list(state["profile"].get("unreadable_columns", [])),
            "suggested_questions": [str(item["question"]) for item in examples[:SUGGESTED_QUESTIONS]],
        }

    def _restore(self, pack: str, state: dict) -> None:
        """Put the previous pack directory back after a failed compile; the live indices were never switched."""
        if not state.get("swapped"):
            return
        target = self._packs_dir / pack
        shutil.rmtree(target, ignore_errors=True)
        if state.get("previous"):
            state["previous"].rename(target)
