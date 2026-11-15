"""Join paths of an instant pack (DECISIONS §5 relationships.yaml, §11 step 0).

A foreign key the source declares between two selected tables is an approved join path between their marts, with
the catalog as evidence. A join-key candidate of the profiler (a column name shared by two marts whose values
overlap) is only a draft: it is never compiled until a person approves it, so the LLM never invents a join.
A candidate becomes a draft only when one side's values are unique (it is the referenced side, many to one) and at
least ``MIN_OVERLAP`` of the other side's values are found there; a column already joined by a foreign key is left out.
"""

from collections.abc import Iterable, Sequence

from app.onboarding.marts import MartTable, mart_name, safe_column

MIN_OVERLAP = 0.95


def source_relationships(source: str, tables: Sequence[MartTable], datasets: set[str]) -> list[dict]:
    """Approved join paths from the foreign keys between ``tables`` whose marts are both in ``datasets``."""
    selected = {table.name for table in tables}
    found = []
    for table in tables:
        for key in table.foreign_keys:
            left, right = mart_name(source, table.name), mart_name(source, key.ref_table)
            if key.ref_table not in selected or left not in datasets or right not in datasets:
                continue
            columns = "_".join(safe_column(column).lower() for column in key.columns)
            found.append({
                "id": f"{left}__{columns}",
                "description": f"Each row of {table.name} references one row of {key.ref_table} by {', '.join(key.columns)}.",
                "from_dataset": left, "to_dataset": right,
                "on": [{"from_column": safe_column(column), "to_column": safe_column(ref)}
                       for column, ref in zip(key.columns, key.ref_columns, strict=True)],
                "cardinality": "many_to_one", "status": "approved",
                "evidence": [{"kind": "source", "ref": (
                    f"foreign key {table.name}({', '.join(key.columns)}) -> {key.ref_table}({', '.join(key.ref_columns)})")}],
                "confidence": 1.0,
            })
    return found


def _joined(relationships: Iterable[dict]) -> set[frozenset[str]]:
    pairs = set()
    for relationship in relationships:
        for pair in relationship["on"]:
            pairs.add(frozenset({f"{relationship['from_dataset']}.{pair['from_column']}",
                                 f"{relationship['to_dataset']}.{pair['to_column']}"}))
    return pairs


def _unique(profile: dict, ref: str) -> bool:
    table, column = ref.split(".", 1)
    facts = profile["tables"][table]
    return facts["rows"] > 0 and facts["columns"][column]["distinct"] == facts["rows"]


def candidate_relationships(profile: dict, approved: Sequence[dict]) -> list[dict]:
    """Draft join paths from the profile's join-key candidates that no approved path already covers."""
    joined = _joined(approved)
    found = []
    for candidate in profile.get("join_candidates") or []:
        left, right, overlap = candidate["left"], candidate["right"], float(candidate["overlap"])
        if overlap < MIN_OVERLAP or frozenset({left, right}) in joined:
            continue
        if _unique(profile, right):
            many, one = left, right
        elif _unique(profile, left):
            many, one = right, left
        else:
            continue
        (from_dataset, from_column), (to_dataset, to_column) = many.split(".", 1), one.split(".", 1)
        found.append({
            "id": f"{from_dataset}__{from_column.lower()}__candidate",
            "description": f"{from_dataset}.{from_column} may reference {to_dataset}.{to_column}; "
                           "the values overlap, but the source declares no foreign key.",
            "from_dataset": from_dataset, "to_dataset": to_dataset,
            "on": [{"from_column": from_column, "to_column": to_column}], "cardinality": "many_to_one",
            "status": "draft", "evidence": [{"kind": "profile", "ref": many}], "confidence": round(overlap, 3),
        })
    return found
