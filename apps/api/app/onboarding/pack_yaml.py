"""Edit Domain Pack YAML files without losing what a person wrote (DECISIONS §11 steps 4-6).

The drafter and the Review API change one item at a time through
``PackFiles``, a round-trip editor over ruamel.yaml that keeps comments,
anchors and aliases, quoting, flow style and item order. A file nothing
changed is never rewritten; a changed file keeps every flow list on one line,
because the hand wrapping of long lists cannot be reproduced. A draft never replaces an approved
item, and editing an item returns it to ``draft`` so it is approved again
before it compiles. ``save`` checks the whole file against its JSON Schema
first and replaces it atomically, so a refused change leaves it untouched.
The application writes the working tree only; people commit reviewed YAML
through the normal branch and pull request workflow.
"""

from collections.abc import Iterable
from dataclasses import dataclass, field
from io import StringIO
import os
from pathlib import Path

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap

from app.packs.loader import PackValidationError, file_issues

# The list of reviewable items in each pack file.
ITEM_LISTS: dict[str, tuple[str, ...]] = {
    "business_profile.yaml": ("conventions",),
    "datasets.yaml": ("datasets",),
    "glossary.yaml": ("terms",),
    "metrics.yaml": ("metrics",),
    "relationships.yaml": ("relationships",),
    "examples.yaml": ("examples",),
    "policies.yaml": ("roles",),
    "eval.yaml": ("cases",),
}


class ItemNotFound(KeyError):
    """The file has no item with this id."""


@dataclass
class MergeResult:
    added: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    skipped_approved: list[str] = field(default_factory=list)


def _yaml() -> YAML:
    yaml = YAML(typ="rt")
    yaml.preserve_quotes = True
    # Never wrap: a wrapped line could not reproduce the files' own wrapping anyway.
    yaml.width = 4096
    yaml.indent(mapping=2, sequence=4, offset=2)
    return yaml


def _keep_anchors(node: object) -> None:
    """Mark every anchor to be written even when no alias uses it; ruamel drops unused anchors otherwise."""
    anchor = getattr(node, "anchor", None)
    if anchor is not None and anchor.value:
        node.yaml_set_anchor(anchor.value, always_dump=True)
    if isinstance(node, dict):
        for value in node.values():
            _keep_anchors(value)
    elif isinstance(node, list):
        for value in node:
            _keep_anchors(value)


class PackFiles:
    def __init__(self, pack_dir: Path, schema_dir: Path | None = None):
        self.pack_dir = pack_dir
        self.schema_dir = schema_dir or pack_dir.parent / "_schema"
        self._documents: dict[str, CommentedMap] = {}
        self._changed: set[str] = set()

    def _document(self, file: str) -> CommentedMap:
        if file not in ITEM_LISTS:
            raise ItemNotFound(f"{file} is not a pack file")
        if file not in self._documents:
            path = self.pack_dir / file
            text = path.read_text(encoding="utf-8") if path.is_file() else ""
            document = _yaml().load(text) or CommentedMap()
            _keep_anchors(document)
            self._documents[file] = document
        return self._documents[file]

    def items(self, file: str) -> list[CommentedMap]:
        node = self._document(file)
        for key in ITEM_LISTS[file]:
            if node.get(key) is None:
                node[key] = []
            node = node[key]
        return node

    def find(self, file: str, item_id: str) -> CommentedMap:
        for item in self.items(file):
            if item.get("id") == item_id:
                return item
        raise ItemNotFound(f"{file} has no item {item_id!r}")

    def merge_drafts(self, file: str, drafts: Iterable[dict]) -> MergeResult:
        """Append new drafts and refresh existing drafts field by field; an approved item is never touched."""
        result = MergeResult()
        items = self.items(file)
        for draft in drafts:
            try:
                current = self.find(file, draft["id"])
            except ItemNotFound:
                items.append(CommentedMap({**draft, "status": "draft"}))
                self._changed.add(file)
                result.added.append(draft["id"])
                continue
            if current.get("status") == "approved":
                result.skipped_approved.append(draft["id"])
                continue
            for key, value in draft.items():
                if current.get(key) != value:
                    current[key] = value
            current["status"] = "draft"
            self._changed.add(file)
            result.updated.append(draft["id"])
        return result

    def update(self, file: str, item_id: str, fields: dict) -> CommentedMap:
        """Change an item's fields; it returns to ``draft`` until a reviewer approves it again."""
        item = self.find(file, item_id)
        for key, value in fields.items():
            item[key] = value
        item["status"] = "draft"
        self._changed.add(file)
        return item

    def approve(self, file: str, item_id: str) -> CommentedMap:
        item = self.find(file, item_id)
        item["status"] = "approved"
        self._changed.add(file)
        return item

    def delete(self, file: str, item_id: str) -> None:
        items = self.items(file)
        items.remove(self.find(file, item_id))
        self._changed.add(file)

    def text(self, file: str) -> str:
        out = StringIO()
        _yaml().dump(self._document(file), out)
        return out.getvalue()

    def save(self, file: str) -> None:
        """Validate a changed file against its schema, then replace it atomically with LF line endings."""
        if file not in self._changed:
            return
        text = self.text(file)
        issues = file_issues(file, text, self.schema_dir)
        if issues:
            raise PackValidationError(self.pack_dir, issues)
        target = self.pack_dir / file
        staged = target.with_name(f"{file}.tmp")
        staged.write_bytes(text.encode("utf-8"))
        os.replace(staged, target)
        self._changed.discard(file)
