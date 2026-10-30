"""Load one manifest source into ClickHouse ``raw`` tables, all or nothing.

Run with ``docker compose run --rm jobs python -m jobs.load_data --source <name>``.
Each table is downloaded at the manifest's pinned revision, written to
``raw.<table>__loading`` and counted. Only when every table matches its
expected row count is each loading table exchanged into ``raw.<table>``; any
failure drops all loading tables and leaves the published tables untouched.
ClickHouse cannot swap several tables atomically, so readers rely on the
refresh state recorded by the refresh job, not on this ordering alone.
"""

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq
from huggingface_hub import hf_hub_download

from jobs.lib.clickhouse import admin_client
from jobs.lib.manifest import ManifestError, SourceManifest, TableSpec, load_manifest

RAW_DATABASE = "raw"
LOADING_SUFFIX = "__loading"
BATCH_ROWS = 500_000
DEFAULT_DATA_DIR = Path("data/hf")


class LoadError(RuntimeError):
    """A load failed and nothing was published; ``results`` holds the tables counted so far."""

    def __init__(self, message: str, results: list["TableResult"]):
        super().__init__(message)
        self.results = results


@dataclass(frozen=True)
class TableResult:
    name: str
    expected_rows: int
    loaded_rows: int

    @property
    def ok(self) -> bool:
        return self.loaded_rows == self.expected_rows


def clickhouse_type(field: pa.Field) -> str:
    base = _base_type(field.type)
    if base is None:
        raise LoadError(f"column {field.name!r} has unsupported type {field.type}", [])
    return f"Nullable({base})" if field.nullable else base


def _base_type(arrow_type: pa.DataType) -> str | None:
    if pa.types.is_string(arrow_type) or pa.types.is_large_string(arrow_type):
        return "String"
    if pa.types.is_boolean(arrow_type):
        return "Bool"
    if pa.types.is_integer(arrow_type):
        prefix = "Int" if pa.types.is_signed_integer(arrow_type) else "UInt"
        return f"{prefix}{arrow_type.bit_width}"
    if pa.types.is_float32(arrow_type):
        return "Float32"
    if pa.types.is_float64(arrow_type):
        return "Float64"
    if pa.types.is_date32(arrow_type):
        return "Date32"
    if pa.types.is_timestamp(arrow_type):
        timezone = f", '{arrow_type.tz}'" if arrow_type.tz else ""
        return f"DateTime64(6{timezone})"
    return None


def download_table(manifest: SourceManifest, table: TableSpec, data_dir: Path, revision: str) -> Path:
    # hf_hub_download writes to an .incomplete file and moves it into place only
    # when the download finishes, and reuses a complete local copy.
    path = hf_hub_download(
        repo_id=manifest.hf_repo,
        filename=table.file,
        repo_type="dataset",
        revision=revision,
        local_dir=data_dir / manifest.name / revision,
    )
    return Path(path)


def load_source(
    manifest: SourceManifest,
    client,
    data_dir: Path,
    revision: str | None = None,
    download=download_table,
) -> list[TableResult]:
    revision = revision or manifest.revision
    _drop_loading(client, manifest)

    results: list[TableResult] = []
    try:
        for table in manifest.tables:
            path = download(manifest, table, data_dir, revision)
            _load_table(client, table, path)
            loaded = int(client.command(f"SELECT count() FROM {_loading(table.name)}"))
            results.append(TableResult(table.name, table.expected_rows, loaded))
    except Exception as error:
        _drop_loading(client, manifest)
        failed = manifest.tables[len(results)].name
        raise LoadError(f"table {failed!r} failed to load: {error}", results) from error

    mismatched = [r.name for r in results if not r.ok]
    if mismatched:
        _drop_loading(client, manifest)
        raise LoadError(f"row counts do not match the manifest for {mismatched}", results)

    for table in manifest.tables:
        _publish(client, table.name)
    return results


def _load_table(client, table: TableSpec, path: Path) -> None:
    parquet = pq.ParquetFile(path)
    schema = parquet.schema_arrow
    columns = ", ".join(f"{_quote(field.name)} {clickhouse_type(field)}" for field in schema)
    client.command(f"CREATE TABLE {_loading(table.name)} ({columns}) ENGINE = MergeTree ORDER BY tuple()")
    bounds = _bounds(table, schema)
    for batch in parquet.iter_batches(batch_size=BATCH_ROWS):
        if bounds is not None:
            index, start, end = bounds
            values = batch.column(index)
            batch = batch.filter(pc.and_(pc.greater_equal(values, start), pc.less(values, end)))
        if batch.num_rows:
            client.insert_arrow(_loading(table.name), pa.Table.from_batches([batch]))


def _bounds(table: TableSpec, schema: pa.Schema):
    """Return the date-range column index and bounds cast to that column's type."""
    if table.date_range is None:
        return None
    column = table.date_range.column
    if column not in schema.names:
        raise LoadError(f"date_range column {column!r} is not in {table.file}", [])
    arrow_type = schema.field(column).type
    start = pa.scalar(table.date_range.start).cast(arrow_type)
    end = pa.scalar(table.date_range.end).cast(arrow_type)
    return schema.get_field_index(column), start, end


def _publish(client, name: str) -> None:
    loading, target = _loading(name), _target(name)
    if int(client.command(f"EXISTS TABLE {target}")):
        client.command(f"EXCHANGE TABLES {loading} AND {target}")
        client.command(f"DROP TABLE {loading}")
    else:
        client.command(f"RENAME TABLE {loading} TO {target}")


def _drop_loading(client, manifest: SourceManifest) -> None:
    for table in manifest.tables:
        client.command(f"DROP TABLE IF EXISTS {_loading(table.name)}")


def _target(name: str) -> str:
    return f"{_quote(RAW_DATABASE)}.{_quote(name)}"


def _loading(name: str) -> str:
    return f"{_quote(RAW_DATABASE)}.{_quote(name + LOADING_SUFFIX)}"


def _quote(identifier: str) -> str:
    return "`" + identifier.replace("\\", "\\\\").replace("`", "\\`") + "`"


def _print_summary(results: list[TableResult]) -> None:
    print(f"{'table':<24} {'expected':>12} {'loaded':>12}  status")
    for result in results:
        status = "ok" if result.ok else "MISMATCH"
        print(f"{result.name:<24} {result.expected_rows:>12} {result.loaded_rows:>12}  {status}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Load one manifest source into ClickHouse raw tables.")
    parser.add_argument("--source", required=True, help="manifest name under jobs/sources")
    parser.add_argument("--revision", help="override the manifest's pinned revision")
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    args = parser.parse_args(argv)

    try:
        manifest = load_manifest(args.source)
        client = admin_client()
        results = load_source(manifest, client, args.data_dir, args.revision, download=download_table)
    except LoadError as error:
        _print_summary(error.results)
        print(f"Load failed, nothing was published: {error}", file=sys.stderr)
        return 1
    except (ManifestError, RuntimeError) as error:
        print(error, file=sys.stderr)
        return 1

    _print_summary(results)
    print(f"Published {len(results)} tables from {manifest.name} at revision {args.revision or manifest.revision}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
