"""Load a Domain Pack directory and validate it.

Loading reads the eight YAML files, validates each against its JSON Schema in
``packs/_schema``, builds the typed models and checks that every reference
between files, and optionally to the warehouse catalog, resolves. Every problem
is collected and reported at once, each naming the file, the item path and the
field.
"""

from collections.abc import Hashable, Iterable, Iterator
from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Protocol

from jsonschema import Draft202012Validator
from referencing import Registry, Resource
import yaml
from yaml.constructor import ConstructorError

from app.packs.models import PACK_FILES, Example, Pack
from app.packs.policy_compiler import ROW_COUNT_COLUMN, adds_up, check_row_filter


@dataclass(frozen=True)
class PackIssue:
    file: str
    path: str
    message: str

    def __str__(self) -> str:
        return f"{self.file}: {self.path}: {self.message}" if self.path else f"{self.file}: {self.message}"


class PackValidationError(Exception):
    def __init__(self, pack_dir: Path, issues: list[PackIssue]):
        self.issues = issues
        super().__init__(f"Pack {pack_dir.name} is invalid:\n" + "\n".join(f"  {issue}" for issue in issues))


class _PackYamlLoader(yaml.SafeLoader):
    """SafeLoader with YAML 1.2 scalars: dates stay strings and only true/false are booleans.

    YAML 1.1 would read a key such as ``on`` as a boolean and an unquoted date
    as a date object, neither of which the JSON Schemas accept. A key repeated
    in one mapping is an error instead of silently replacing the first value.
    """

    def construct_mapping(self, node: yaml.MappingNode, deep: bool = False) -> dict:
        seen: set[Hashable] = set()
        for key_node, _ in node.value:
            if key_node.tag == "tag:yaml.org,2002:merge":
                continue
            key = self.construct_object(key_node, deep=True)
            if not isinstance(key, Hashable):
                raise ConstructorError("while constructing a mapping", node.start_mark, "found unhashable key", key_node.start_mark)
            if key in seen:
                raise ConstructorError("while constructing a mapping", node.start_mark, f"duplicate key {key!r}", key_node.start_mark)
            seen.add(key)
        return super().construct_mapping(node, deep=deep)


_PackYamlLoader.yaml_implicit_resolvers = {
    first: [
        (tag, pattern) for tag, pattern in resolvers
        if tag not in ("tag:yaml.org,2002:timestamp", "tag:yaml.org,2002:bool")
    ]
    for first, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
}
_PackYamlLoader.add_implicit_resolver(
    "tag:yaml.org,2002:bool", re.compile(r"^(?:true|True|TRUE|false|False|FALSE)$"), list("tTfF")
)


def item_path(parts: Iterable[str | int]) -> str:
    """Format a path such as ``metrics[0].unit``."""
    text = ""
    for part in parts:
        if isinstance(part, int):
            text += f"[{part}]"
        else:
            text += f".{part}" if text else part
    return text


def _validators(schema_dir: Path) -> dict[str, Draft202012Validator]:
    schemas = {path.name: json.loads(path.read_text(encoding="utf-8")) for path in schema_dir.glob("*.schema.json")}
    registry = Registry().with_resources((name, Resource.from_contents(schema)) for name, schema in schemas.items())
    return {
        file: Draft202012Validator(schemas[file.removesuffix(".yaml") + ".schema.json"], registry=registry)
        for file in PACK_FILES
    }


def _schema_issues(file: str, data: object, validator: Draft202012Validator) -> Iterator[PackIssue]:
    for error in validator.iter_errors(data):
        path = list(error.absolute_path)
        if error.validator == "required" and isinstance(error.instance, dict):
            for field in error.validator_value:
                if field not in error.instance:
                    yield PackIssue(file, item_path([*path, field]), "required field is missing")
        elif error.validator == "additionalProperties" and isinstance(error.instance, dict):
            for field in sorted(set(error.instance) - set(error.schema.get("properties", {}))):
                yield PackIssue(file, item_path([*path, field]), "unknown field")
        else:
            yield PackIssue(file, item_path(path), error.message)


def file_issues(file: str, text: str, schema_dir: Path) -> list[PackIssue]:
    """Schema issues of one pack file's text, read with the pack YAML rules."""
    try:
        data = yaml.load(text, Loader=_PackYamlLoader)  # noqa: S506 - SafeLoader subclass
    except yaml.YAMLError as error:
        return [PackIssue(file, "", f"invalid YAML: {error}")]
    return list(_schema_issues(file, data, _validators(schema_dir)[file]))


def read_yaml(path: Path) -> object:
    """Parse one pack file with the pack YAML rules."""
    return yaml.load(path.read_text(encoding="utf-8"), Loader=_PackYamlLoader)  # noqa: S506 - SafeLoader subclass


class Catalog(Protocol):
    """Read access to the warehouse tables that the pack's datasets describe."""

    def table_columns(self, table: str) -> set[str] | None:
        """Return the column names of a marts table, or None when the table does not exist."""


class _References:
    """Collects cross-reference problems for one loaded pack."""

    def __init__(self, pack: Pack):
        self.pack = pack
        self.issues: list[PackIssue] = []
        self.datasets = {item.id: {column.name for column in item.columns} for item in pack.datasets.datasets}
        self.metrics = {item.id for item in pack.metrics.metrics}
        self.roles = {item.id for item in pack.policies.roles}

    def add(self, file: str, path: list[str | int], message: str) -> None:
        self.issues.append(PackIssue(file, item_path(path), message))

    def metric(self, file: str, path: list[str | int], metric_id: str | None) -> None:
        if metric_id is not None and metric_id not in self.metrics:
            self.add(file, path, f"unknown metric '{metric_id}'")

    def dataset(self, file: str, path: list[str | int], dataset_id: str | None) -> bool:
        """Report an unknown dataset; return whether its columns can be checked."""
        if dataset_id is None:
            return False
        if dataset_id not in self.datasets:
            self.add(file, path, f"unknown dataset '{dataset_id}'")
            return False
        return True

    def column(self, file: str, path: list[str | int], dataset_id: str, column: str | None) -> None:
        if column is not None and column not in self.datasets[dataset_id]:
            self.add(file, path, f"unknown column '{column}' in dataset '{dataset_id}'")

    def row_filter(self, path: list[str | int], dataset_id: str, text: str) -> None:
        problem = check_row_filter(text, self.datasets[dataset_id])
        if problem is not None and problem.startswith("unknown column"):
            problem += f" in dataset '{dataset_id}'"
        if problem is not None:
            self.add("policies.yaml", path, problem)

    def aggregate_only(self, path: list[str | int], dataset_id: str, columns: list[str], metrics: list[str]) -> None:
        """Check an aggregate-only grant: its metrics belong to the dataset and its view's column names are unique."""
        defined = {metric.id: metric for metric in self.pack.metrics.metrics}
        for number, metric_id in enumerate(metrics):
            metric = defined.get(metric_id)
            if metric is None:
                self.add("policies.yaml", [*path, "metrics", number], f"unknown metric '{metric_id}'")
            elif metric.dataset != dataset_id:
                self.add(
                    "policies.yaml", [*path, "metrics", number],
                    f"metric '{metric_id}' is computed from dataset '{metric.dataset}', not '{dataset_id}'",
                )
            elif not adds_up(metric.sql_expr):
                self.add(
                    "policies.yaml", [*path, "metrics", number],
                    f"metric '{metric_id}' must be one sum or count, so that its values add up across the view's groups",
                )
        names = [*columns, *metrics, ROW_COUNT_COLUMN]
        if repeated := sorted({name for name in names if names.count(name) > 1}):
            self.add("policies.yaml", path, f"the view would have more than one column named {', '.join(repeated)}")

    def example_spec(self, path: list[str | int], example: Example) -> None:
        """Check a reviewed spec: one dataset, its columns, single-value operators and a ranking by one of its metrics."""
        spec, path = example.spec, [*path, "spec"]
        if len(example.datasets) != 1:
            self.add("examples.yaml", path, "an example with a spec names exactly one dataset")
            return
        dataset_id = example.datasets[0]
        if dataset_id not in self.datasets:
            return
        defined = {metric.id: metric.dataset for metric in self.pack.metrics.metrics}
        for position, metric_id in enumerate(example.metrics):
            if defined.get(metric_id, dataset_id) != dataset_id:
                self.add("examples.yaml", [*path[:-1], "metrics", position],
                         f"metric '{metric_id}' is computed from dataset '{defined[metric_id]}', not '{dataset_id}'")
        for position, column in enumerate(spec.dimensions):
            self.column("examples.yaml", [*path, "dimensions", position], dataset_id, column)
        for position, item in enumerate(spec.filters):
            self.column("examples.yaml", [*path, "filters", position, "column"], dataset_id, item.column)
            if item.op in ("=", "!=") and len(item.values) != 1:
                self.add("examples.yaml", [*path, "filters", position, "values"], f"operator '{item.op}' takes exactly one value")
        if spec.rank_by is not None and spec.rank_by not in example.metrics:
            self.add("examples.yaml", [*path, "rank_by"], "must be one of the example's metrics")

    def unique_ids(self, file: str, key: str, items: Iterable[object]) -> None:
        seen: set[str] = set()
        for index, item in enumerate(items):
            if item.id in seen:
                self.add(file, [key, index, "id"], f"duplicate id '{item.id}'")
            seen.add(item.id)


def check_references(pack: Pack, catalog: Catalog | None = None) -> list[PackIssue]:
    """Check that every reference between pack files, and to the catalog when given, resolves."""
    refs = _References(pack)
    profile = pack.business_profile
    if profile.name != pack.name:
        refs.add("business_profile.yaml", ["name"], f"must equal the pack directory name '{pack.name}'")
    refs.unique_ids("business_profile.yaml", "conventions", profile.conventions)
    for index, convention in enumerate(profile.conventions):
        refs.metric("business_profile.yaml", ["conventions", index, "metric"], convention.metric)

    datasets = pack.datasets.datasets
    refs.unique_ids("datasets.yaml", "datasets", datasets)
    for index, dataset in enumerate(datasets):
        path: list[str | int] = ["datasets", index]
        names: set[str] = set()
        for position, column in enumerate(dataset.columns):
            if column.name in names:
                refs.add("datasets.yaml", [*path, "columns", position, "name"], f"duplicate column '{column.name}'")
            names.add(column.name)
            if column.indexable and column.type != "string":
                refs.add("datasets.yaml", [*path, "columns", position, "indexable"], "only string columns can be indexable")
        if not any(column.name == dataset.time_column and column.role == "time" for column in dataset.columns):
            refs.add("datasets.yaml", [*path, "time_column"], "must name a column with role time")
        granted = [role.id for role in pack.policies.roles if any(grant.dataset == dataset.id for grant in role.datasets)]
        if set(dataset.allowed_roles) != set(granted):
            refs.add(
                "datasets.yaml", [*path, "allowed_roles"],
                f"must equal the roles granted this dataset in policies.yaml: {granted}",
            )

    refs.unique_ids("glossary.yaml", "terms", pack.glossary.terms)
    for index, term in enumerate(pack.glossary.terms):
        for position, target in enumerate(term.targets):
            path = ["terms", index, "targets", position]
            refs.metric("glossary.yaml", [*path, "metric"], target.metric)
            if refs.dataset("glossary.yaml", [*path, "dataset"], target.dataset):
                refs.column("glossary.yaml", [*path, "column"], target.dataset, target.column)

    refs.unique_ids("metrics.yaml", "metrics", pack.metrics.metrics)
    for index, metric in enumerate(pack.metrics.metrics):
        refs.dataset("metrics.yaml", ["metrics", index, "dataset"], metric.dataset)

    refs.unique_ids("relationships.yaml", "relationships", pack.relationships.relationships)
    for index, relationship in enumerate(pack.relationships.relationships):
        path = ["relationships", index]
        from_known = refs.dataset("relationships.yaml", [*path, "from_dataset"], relationship.from_dataset)
        to_known = refs.dataset("relationships.yaml", [*path, "to_dataset"], relationship.to_dataset)
        for position, pair in enumerate(relationship.on):
            if from_known:
                refs.column("relationships.yaml", [*path, "on", position, "from_column"], relationship.from_dataset, pair.from_column)
            if to_known:
                refs.column("relationships.yaml", [*path, "on", position, "to_column"], relationship.to_dataset, pair.to_column)

    refs.unique_ids("examples.yaml", "examples", pack.examples.examples)
    for index, example in enumerate(pack.examples.examples):
        for position, dataset_id in enumerate(example.datasets):
            refs.dataset("examples.yaml", ["examples", index, "datasets", position], dataset_id)
        for position, metric_id in enumerate(example.metrics):
            refs.metric("examples.yaml", ["examples", index, "metrics", position], metric_id)
        if example.spec is not None:
            refs.example_spec(["examples", index], example)

    refs.unique_ids("policies.yaml", "roles", pack.policies.roles)
    for index, role in enumerate(pack.policies.roles):
        granted: set[str] = set()
        for position, grant in enumerate(role.datasets):
            path = ["roles", index, "datasets", position]
            if grant.dataset in granted:
                refs.add("policies.yaml", [*path, "dataset"], f"dataset '{grant.dataset}' is granted to this role more than once")
            granted.add(grant.dataset)
            if not refs.dataset("policies.yaml", [*path, "dataset"], grant.dataset):
                continue
            for number, column in enumerate(grant.columns):
                refs.column("policies.yaml", [*path, "columns", number], grant.dataset, column)
            if grant.row_filter is not None:
                refs.row_filter([*path, "row_filter"], grant.dataset, grant.row_filter)
            if grant.aggregate_only is not None:
                refs.aggregate_only([*path, "aggregate_only"], grant.dataset, grant.columns, grant.aggregate_only.metrics)

    refs.unique_ids("eval.yaml", "cases", pack.eval.cases)
    for index, case in enumerate(pack.eval.cases):
        path = ["cases", index]
        if case.role not in refs.roles:
            refs.add("eval.yaml", [*path, "role"], f"unknown role '{case.role}'")
        expected = case.expected
        for position, metric_id in enumerate(expected.metrics):
            refs.metric("eval.yaml", [*path, "expected", "metrics", position], metric_id)
        refs.metric("eval.yaml", [*path, "expected", "rank_by"], expected.rank_by)
        if refs.dataset("eval.yaml", [*path, "expected", "dataset"], expected.dataset):
            for position, column in enumerate(expected.columns):
                refs.column("eval.yaml", [*path, "expected", "columns", position], expected.dataset, column)
        if case.expected_sql is not None and case.expected_rows is not None:
            refs.add("eval.yaml", [*path, "expected_rows"], "set either expected_sql or expected_rows, not both")
        if case.expected_rows:
            columns = set(case.expected_rows[0])
            for position, row in enumerate(case.expected_rows[1:], start=1):
                if set(row) != columns:
                    refs.add(
                        "eval.yaml", [*path, "expected_rows", position],
                        f"must name the columns of the first row: {', '.join(sorted(columns))}",
                    )

    if catalog is not None:
        for index, dataset in enumerate(datasets):
            columns = catalog.table_columns(dataset.id)
            if columns is None:
                refs.add("datasets.yaml", ["datasets", index, "id"], f"table '{dataset.id}' not found in the warehouse")
                continue
            for position, column in enumerate(dataset.columns):
                if column.name not in columns:
                    refs.add(
                        "datasets.yaml", ["datasets", index, "columns", position, "name"],
                        f"column '{column.name}' not found in table '{dataset.id}'",
                    )
    return refs.issues


def load_pack(pack_dir: Path, *, schema_dir: Path | None = None, catalog: Catalog | None = None) -> Pack:
    """Load and validate the pack in ``pack_dir``; raise PackValidationError listing every problem.

    Without a catalog, dataset columns are not checked against the warehouse.
    """
    validators = _validators(schema_dir or pack_dir.parent / "_schema")
    contents: dict[str, object] = {}
    issues: list[PackIssue] = []
    for file, validator in validators.items():
        path = pack_dir / file
        if not path.is_file():
            issues.append(PackIssue(file, "", "file is missing"))
            continue
        try:
            data = read_yaml(path)
        except yaml.YAMLError as error:
            issues.append(PackIssue(file, "", "invalid YAML: " + " ".join(str(error).split())))
            continue
        issues.extend(sorted(dict.fromkeys(_schema_issues(file, data, validator)), key=lambda issue: issue.path))
        contents[file.removesuffix(".yaml")] = data
    if issues:
        raise PackValidationError(pack_dir, issues)
    pack = Pack(name=pack_dir.name, **contents)
    issues = check_references(pack, catalog)
    if issues:
        raise PackValidationError(pack_dir, issues)
    return pack
