"""The deterministic files of an instant pack (DECISIONS §5, §11 step 0); the drafter fills them afterwards.

From the mart views and their profile:

- ``datasets.yaml``: one dataset per view with a time column, wide views first because they hold the joined
  columns the agent needs. A number is a measure, a date or a date and time is time, and text, booleans and key
  columns are dimensions; a string column with at most ``INDEXED_VALUES`` values, other than a key, is indexable so
  its values can be matched in filters. Descriptions are left for the drafter (``status: draft``).
- ``business_profile.yaml`` with neutral defaults and no convention, ``policies.yaml`` with one role reading every
  column of every dataset, and ``relationships.yaml`` with the source's foreign keys (approved) and the profile's
  join-key candidates (drafts).
- empty glossary, metrics and examples for the drafter, and no ``eval.yaml``.

A view without a time column gets no dataset, because every dataset needs one; the summary lists it.
"""

from collections.abc import Sequence
from pathlib import Path

import yaml

from app.onboarding.marts import MartTable, MartView
from app.onboarding.pack_yaml import PackFiles
from app.onboarding.relationships import candidate_relationships, source_relationships

READER_ROLE = "reader"
INDEXED_VALUES = 1000
TO_DRAFT = "Description to draft."
DEFAULT_CURRENCY = "USD"
GENERATED = {"kind": "manual", "ref": "generated with the instant pack"}
_ROLES = {"number": "measure", "date": "time", "datetime": "time"}


def _columns(view: MartView, facts: dict) -> list[dict]:
    keys = set(view.keys)
    columns = []
    for name in view.columns:
        fact = facts["columns"].get(name, {"type": "string", "distinct": 0})
        kind = fact["type"] if fact["type"] != "other" else "string"
        role = "dimension" if name in keys and kind not in ("date", "datetime") else _ROLES.get(kind, "dimension")
        column = {"name": name, "type": kind, "role": role, "description": TO_DRAFT}
        if kind == "string" and name not in keys and 0 < fact["distinct"] <= INDEXED_VALUES:
            column["indexable"] = True
        columns.append(column)
    return columns


def dataset_items(views: Sequence[MartView], profile: dict) -> list[dict]:
    """A draft dataset for each profiled view that has a time column, the wide views first."""
    items = []
    for view in sorted(views, key=lambda view: not view.wide):
        facts = profile["tables"].get(view.name)
        if facts is None:
            continue
        columns = _columns(view, facts)
        times = [column["name"] for column in columns if column["role"] == "time"]
        if not times:
            continue
        grain = (f"One row of {view.table}, with the columns of the tables it references" if view.wide
                 else f"One row of {view.table}")
        items.append({
            "id": view.name, "description": TO_DRAFT, "grain": grain, "time_column": times[0],
            "allowed_roles": [READER_ROLE], "columns": columns, "status": "draft",
            "evidence": [{"kind": "profile", "ref": view.name}], "confidence": 0.5,
        })
    return items


def _dump(path: Path, data: dict) -> None:
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True, width=4096), encoding="utf-8")


def write_pack_files(pack_dir: Path, *, pack: str, display_name: str, source: str, tables: Sequence[MartTable],
                     views: Sequence[MartView], profile: dict, currency: str = DEFAULT_CURRENCY) -> dict:
    """Write the pack's files into ``pack_dir``, replacing any there; returns what was written."""
    pack_dir.mkdir(parents=True, exist_ok=True)
    datasets = dataset_items(views, profile)
    listed = {item["id"] for item in datasets}
    approved = source_relationships(source, tables, listed)
    relationships = approved + [item for item in candidate_relationships(profile, approved)
                                if item["from_dataset"] in listed and item["to_dataset"] in listed]
    files = {
        "business_profile.yaml": {"name": pack, "display_name": display_name, "industry": "not specified",
                                  "currency": currency, "fiscal_year_start_month": 1, "conventions": []},
        "datasets.yaml": {"datasets": datasets},
        "policies.yaml": {"roles": [{
            "id": READER_ROLE, "description": "Reads every column of every dataset.",
            "datasets": [{"dataset": item["id"], "columns": [column["name"] for column in item["columns"]]}
                         for item in datasets],
            "status": "approved", "evidence": [GENERATED], "confidence": 1.0,
        }]},
        "relationships.yaml": {"relationships": relationships},
        "glossary.yaml": {"terms": []},
        "metrics.yaml": {"metrics": []},
        "examples.yaml": {"examples": []},
    }
    for file, data in files.items():
        _dump(pack_dir / file, data)
    (pack_dir / "eval.yaml").unlink(missing_ok=True)
    return {"datasets": len(datasets), "relationships": len(relationships),
            "skipped": [view.name for view in views if view.name not in listed]}


# Files whose drafts an instant pack approves, in an order where an item comes after those it may cite.
APPROVED_FILES = ("datasets.yaml", "metrics.yaml", "glossary.yaml", "examples.yaml", "policies.yaml", "relationships.yaml")


def _cites(file: str, item: dict, dropped_metrics: set[str]) -> bool:
    if file == "glossary.yaml":
        return any(target.get("metric") in dropped_metrics for target in item.get("targets") or [])
    if file == "examples.yaml":
        return any(metric in dropped_metrics for metric in item.get("metrics") or [])
    return False


def approve_generated(pack_dir: Path, schema_dir: Path | None = None) -> dict:
    """Approve the pack's generated items as unreviewed (``reviewed: false``), as an instant pack does.

    A draft whose test-run failed (an ``error`` evidence) is dropped, and so is a glossary term or an example that
    cites a dropped metric. Draft join paths stay drafts: a join the source does not declare needs a person.
    """
    files = PackFiles(pack_dir, schema_dir=schema_dir)
    dropped: list[str] = []
    dropped_metrics: set[str] = set()
    for file in APPROVED_FILES:
        for item in list(files.items(file)):
            failed = any(evidence.get("kind") == "error" for evidence in item.get("evidence") or [])
            if failed or _cites(file, item, dropped_metrics):
                files.delete(file, item["id"])
                dropped.append(f"{file.removesuffix('.yaml')}.{item['id']}")
                if file == "metrics.yaml":
                    dropped_metrics.add(item["id"])
                continue
            if file == "relationships.yaml" and item.get("status") != "approved":
                continue
            files.approve(file, item["id"])["reviewed"] = False
        files.save(file)
    return {"dropped": dropped}
