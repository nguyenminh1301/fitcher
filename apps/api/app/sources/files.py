"""Upload a CSV, XLSX or Parquet file and load it into ``raw`` (DECISIONS §4 Data sources).

The file type comes from the content, never the name: Parquet by its magic bytes, XLSX as the document parser
decides (macro-enabled workbooks are refused), anything else must be UTF-8 text and is read as CSV. The body is
written to the data directory while it is counted against the size cap, so a large upload never sits in memory,
and the original stays there so the table can be reloaded.

ClickHouse infers the column types of a CSV from a sample, and the Parquet schema comes from the file; the page
shows them for confirmation before anything is loaded. The load streams the file through the client into a
loading table and swaps it in, so it works with an external ClickHouse that cannot see the api's disk. XLSX is
read with openpyxl in read-only mode, first sheet only, and sent as CSV; formulas are not evaluated.
"""

import csv
from datetime import UTC, date, datetime, time
import hashlib
from io import BytesIO, StringIO
import logging
from pathlib import Path
import re
import secrets
import shutil
import unicodedata
from typing import BinaryIO, Iterator

from app.onboarding.docs_parser import DocumentRejected, _office_type, XLSX
from app.sources.attach import Source, Table, loading_table, publish_copy, quote, raw_relation, raw_table, valid_name
from app.sources.store import (
    DuplicateSource, NewSource, SourceStore, StoredFile, StoredSource, TableChange,
)
from app.sources.inspect import CatalogColumn, TableInfo

logger = logging.getLogger(__name__)

HEAD_BYTES = 64 * 1024
CHUNK_BYTES = 1024 * 1024
SAMPLE_ROWS = 5
INFERENCE_ROWS = 1000
MAX_TABLE_NAME = 40
DELIMITERS = (",", ";", "\t", "|")
# A column type is interpolated into DDL, so only these shapes pass.
_TYPE = re.compile(
    r"^(?:Nullable\()?(?:U?Int(?:8|16|32|64)|Float(?:32|64)|Bool|String|Date|Date32|DateTime|DateTime64\(\d(?:, '[A-Za-z_/+-]+')?\)"
    r"|Decimal\(\d{1,2}, \d{1,2}\))\)?$"
)


class FileTooLarge(ValueError):
    pass


class UploadNotFound(LookupError):
    pass


class LoadFailed(RuntimeError):
    """ClickHouse refused the rows; the cause is not repeated because it can quote the data."""


class FileColumn:
    __slots__ = ("name", "type")

    def __init__(self, name: str, type: str):
        self.name, self.type = name, type

    def __eq__(self, other: object) -> bool:
        return isinstance(other, FileColumn) and (self.name, self.type) == (other.name, other.type)

    def __repr__(self) -> str:
        return f"FileColumn({self.name!r}, {self.type!r})"


class Upload:
    def __init__(self, id: str, file_name: str, format: str, size_bytes: int, columns: list[FileColumn],
                 sample: list[list[str | None]]):
        self.id, self.file_name, self.format, self.size_bytes = id, file_name, format, size_bytes
        self.columns, self.sample = columns, sample


# Type from the content


def _decodes(head: bytes) -> bool:
    import codecs

    try:
        codecs.getincrementaldecoder("utf-8-sig")().decode(head, final=False)
        return True
    except UnicodeDecodeError:
        return False


def detect_format(data: bytes | BinaryIO, file_name: str) -> str:
    """``csv``, ``xlsx`` or ``parquet`` from the content of ``data`` (bytes or a seekable file)."""
    source = BytesIO(data) if isinstance(data, bytes) else data
    source.seek(0, 2)
    size = source.tell()
    source.seek(0)
    head = source.read(HEAD_BYTES)
    if size == 0:
        raise DocumentRejected("the file is empty")
    if head.startswith(b"PAR1"):
        source.seek(-4, 2)
        if source.read(4) != b"PAR1":
            raise DocumentRejected("the Parquet file is incomplete", 415)
        return "parquet"
    if head.startswith(b"PK\x03\x04"):
        source.seek(0)
        if _office_type(source) != XLSX:
            raise DocumentRejected("only XLSX workbooks are accepted among Office files", 415)
        return "xlsx"
    if head.startswith(b"%PDF-") or b"\x00" in head[:8192]:
        raise DocumentRejected("the file is not a CSV, XLSX or Parquet file", 415)
    if not _decodes(head):
        raise DocumentRejected("a CSV file must be UTF-8 text")
    return "csv"


# Names and columns


def table_name(file_name: str) -> str:
    """A lower-case identifier for the table of a file: accents removed, other characters become underscores."""
    stem = Path(file_name).name.rsplit(".", 1)[0] if "." in Path(file_name).name else Path(file_name).name
    folded = unicodedata.normalize("NFKD", stem.replace("đ", "d").replace("Đ", "D"))
    ascii_text = "".join(c for c in folded if not unicodedata.combining(c)).lower()
    slug = re.sub(r"[^a-z0-9]+", "_", ascii_text).strip("_")[:MAX_TABLE_NAME].strip("_")
    if not slug:
        return "data"
    return slug if slug[0].isalpha() else f"f_{slug}"[:MAX_TABLE_NAME]


def normalize_header(names: list[str]) -> list[str]:
    """Trim each name, name an empty one ``column_N`` and suffix a repeated one ``_2``, ``_3``."""
    result: list[str] = []
    seen: dict[str, int] = {}
    for position, name in enumerate(names, start=1):
        base = (name or "").strip() or f"column_{position}"
        count = seen.get(base, 0) + 1
        seen[base] = count
        result.append(base if count == 1 else f"{base}_{count}")
    return result


def check_columns(columns: list[FileColumn]) -> None:
    if not columns:
        raise ValueError("the file needs at least one column")
    names = [column.name for column in columns]
    if any(not name.strip() for name in names):
        raise ValueError("every column needs a name")
    if len(set(names)) != len(names):
        raise ValueError("column names must be unique")
    for column in columns:
        if not _TYPE.match(column.type):
            raise ValueError(f"the type {column.type!r} of column {column.name!r} is not one of the supported column types")


# Readers


def _cell(value) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        # A spreadsheet stores a date as a moment at midnight; keep it a date so ClickHouse infers Date.
        if value.time() == time(0, 0):
            return value.date().isoformat()
        return value.isoformat(sep=" ") if value.microsecond else value.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(value, (date, time)):
        return value.isoformat()
    return str(value)


def workbook_rows(data: bytes | BinaryIO) -> tuple[list[str], Iterator[list[str]]]:
    """The header and the rows of the first sheet with data, as text; formulas show their cached values."""
    from openpyxl import load_workbook

    try:
        book = load_workbook(BytesIO(data) if isinstance(data, bytes) else data, read_only=True, data_only=True)
    except Exception as error:  # noqa: BLE001 - openpyxl raises many types for a corrupt workbook
        raise DocumentRejected(f"the workbook cannot be read: {type(error).__name__}") from None
    for sheet in book.worksheets:
        rows = sheet.iter_rows(values_only=True)
        header = None
        for row in rows:
            if any(cell not in (None, "") for cell in row):
                header = normalize_header([_cell(cell) for cell in row])
                break
        if header is None:
            continue

        def body(rows=rows, width=len(header), book=book) -> Iterator[list[str]]:
            try:
                for row in rows:
                    cells = [_cell(cell) for cell in row][:width]
                    if any(cells):
                        yield cells + [""] * (width - len(cells))
            finally:
                book.close()

        return header, body()
    book.close()
    raise DocumentRejected("the workbook has no sheet with data")


_ARROW = {
    "string": "String", "large_string": "String", "bool": "Bool", "float": "Float32", "double": "Float64",
    "date32[day]": "Date32", "date64[ms]": "Date32",
}


def _arrow_type(field) -> str:
    import pyarrow as pa

    kind = field.type
    if pa.types.is_integer(kind):
        return f"{'Int' if pa.types.is_signed_integer(kind) else 'UInt'}{kind.bit_width}"
    if pa.types.is_timestamp(kind):
        zone = f", '{kind.tz}'" if kind.tz and re.fullmatch(r"[A-Za-z_/+-]+", kind.tz) else ""
        return f"DateTime64(6{zone})"
    if pa.types.is_decimal(kind) and kind.precision <= 76:
        return f"Decimal({min(kind.precision, 38)}, {min(kind.scale, 38)})"
    return _ARROW.get(str(kind), "String")


def parquet_columns(data: bytes | BinaryIO) -> list[FileColumn]:
    import pyarrow.parquet as pq

    schema = pq.read_schema(BytesIO(data) if isinstance(data, bytes) else data)
    return [FileColumn(field.name, f"Nullable({_arrow_type(field)})") for field in schema]


def _csv_text(header: list[str], rows: list[list[str]]) -> str:
    buffer = StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(header)
    writer.writerows(rows)
    return buffer.getvalue()


def _sniff_delimiter(head: str) -> str:
    first = head.splitlines()[0] if head.strip() else ""
    counts = {delimiter: first.count(delimiter) for delimiter in DELIMITERS}
    best = max(counts, key=counts.get)
    return best if counts[best] else ","


def _read_csv_head(path: Path) -> tuple[str, str]:
    """The delimiter and the first ``INFERENCE_ROWS`` rows of a CSV file, ending on a whole line."""
    with path.open("rb") as handle:
        raw = handle.read(HEAD_BYTES)
    text = raw.decode("utf-8-sig", errors="ignore")
    if len(raw) == HEAD_BYTES and "\n" in text:
        text = text[: text.rindex("\n") + 1]
    delimiter = _sniff_delimiter(text)
    reader = list(csv.reader(StringIO(text), delimiter=delimiter))[: INFERENCE_ROWS + 1]
    if not reader:
        raise DocumentRejected("the CSV file has no header row")
    header = normalize_header(reader[0])
    return delimiter, _csv_text(header, [row + [""] * (len(header) - len(row)) for row in reader[1:]])


class FileService:
    def __init__(self, store: SourceStore, client, directory: Path, max_bytes: int):
        self._store = store
        self._client = client
        self._directory = Path(directory)
        self.max_bytes = max_bytes

    # Upload

    def upload(self, file_name: str, body: BinaryIO, uploaded_by: str | None) -> Upload:
        file_id = secrets.token_hex(8)
        folder = self._directory / file_id
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / "original"
        try:
            size, digest = self._write(body, path)
            with path.open("rb") as handle:
                kind = detect_format(handle, file_name)
            columns, sample = self._infer(kind, path)
        except BaseException:
            shutil.rmtree(folder, ignore_errors=True)
            raise
        self._store.add_file(StoredFile(
            id=file_id, source_id=None, file_name=file_name, format=kind, size_bytes=size, sha256=digest,
            columns=tuple((c.name, c.type) for c in columns), stored_path=str(path), uploaded_by=uploaded_by,
            created_at=datetime.now(UTC).isoformat()))
        return Upload(file_id, file_name, kind, size, columns, sample)

    def _write(self, body: BinaryIO, path: Path) -> tuple[int, str]:
        digest, size = hashlib.sha256(), 0
        with path.open("wb") as out:
            while chunk := body.read(CHUNK_BYTES):
                size += len(chunk)
                if size > self.max_bytes:
                    raise FileTooLarge(f"the file is larger than {self.max_bytes} bytes")
                digest.update(chunk)
                out.write(chunk)
        return size, digest.hexdigest()

    def _infer(self, kind: str, path: Path) -> tuple[list[FileColumn], list[list[str | None]]]:
        if kind == "parquet":
            import pyarrow.parquet as pq

            columns = parquet_columns(path.open("rb"))
            sample = pq.ParquetFile(path).read_row_group(0).slice(0, SAMPLE_ROWS).to_pylist() if pq.ParquetFile(path).num_row_groups else []
            return columns, [[None if row[c.name] is None else str(row[c.name]) for c in columns] for row in sample]
        if kind == "xlsx":
            header, rows = workbook_rows(path.open("rb"))
            kept = []
            for row in rows:
                kept.append(row)
                if len(kept) >= INFERENCE_ROWS:
                    break
            sample_text, delimiter = _csv_text(header, kept), ","
        else:
            delimiter, sample_text = _read_csv_head(path)
        result = self._client.query(
            "DESCRIBE TABLE format(CSVWithNames, {sample:String})", parameters={"sample": sample_text},
            settings={"format_csv_delimiter": delimiter if kind == "csv" else ",", "schema_inference_make_columns_nullable": 1,
                      "input_format_csv_use_best_effort_in_schema_inference": 1})
        columns = [FileColumn(row[0], row[1]) for row in result.result_rows]
        parsed = list(csv.reader(StringIO(sample_text)))[1:][:SAMPLE_ROWS]
        return columns, parsed

    # Load

    def load(self, file_id: str, name: str | None, columns: list[FileColumn]) -> StoredSource:
        stored = self._store.get_file(file_id)
        if stored is None or stored.source_id is not None:
            raise UploadNotFound(f"no pending upload {file_id!r}")
        if [c.name for c in columns] != [n for n, _ in stored.columns]:
            raise ValueError("the confirmed columns must be the columns of the file, in order")
        check_columns(columns)
        source_id = name or table_name(stored.file_name)
        if not valid_name(source_id):
            raise ValueError(f"{source_id!r} is not a valid source name")
        if any(source.id == source_id for source in self._store.list()):
            raise DuplicateSource(f"a source named {source_id!r} already exists")
        table = Table(source_id)
        source = Source(source_id, "file", (table,))
        rows = self._stream(source, table, stored, columns)
        try:
            created = self._store.create(NewSource(id=source_id, kind="file"))
            self._store.save_catalog(source_id, [TableInfo(
                source_id, "table", rows, stored.size_bytes,
                columns=tuple(CatalogColumn(c.name, c.type, c.type.startswith("Nullable"), i)
                              for i, c in enumerate(columns, start=1)))])
            self._store.set_tables(source_id, [TableChange(source_id, selected=True, mode="copy")])
            self._store.attach_file(file_id, source_id, tuple((c.name, c.type) for c in columns))
            self._record(source_id, rows, "setup")
        except BaseException:
            self._drop(source)
            raise
        return created

    def _record(self, source_id: str, rows: int, started_by: str) -> None:
        now = datetime.now(UTC)
        sync = self._store.start_sync(source_id, started_by, now)
        self._store.record_table_sync(source_id, source_id, rows=rows, cursor_value=None,
                                      next_run_at=now.replace(year=now.year + 100), synced_at=now)
        self._store.finish_sync(sync.id, "succeeded", finished_at=now,
                                results=[{"table": source_id, "mode": "copy", "rows": rows, "full": True}], error=None)

    def _drop(self, source: Source) -> None:
        for table in source.tables:
            self._client.command(f"DROP TABLE IF EXISTS {raw_relation(source, table)}")

    def _stream(self, source: Source, table: Table, stored: StoredFile, columns: list[FileColumn]) -> int:
        """Stage the file in a loading table and publish it; a failure leaves the published copy as it was."""
        loading = loading_table(raw_table(source, table))
        structure = ", ".join(f"{quote(c.name)} {c.type}" for c in columns)
        self._client.command(f"DROP TABLE IF EXISTS {loading}")
        try:
            self._client.command(f"CREATE TABLE {loading} ({structure}) ENGINE = MergeTree ORDER BY tuple()")
            self._insert(loading, stored)
            rows = int(self._client.command(f"SELECT count() FROM {loading}"))
        except Exception:
            self._client.command(f"DROP TABLE IF EXISTS {loading}")
            logger.warning("loading the uploaded file %s failed", stored.id)
            raise LoadFailed("ClickHouse could not load the file with these column types") from None
        publish_copy(self._client, source, table)
        return rows

    def _insert(self, loading: str, stored: StoredFile) -> None:
        path = Path(stored.stored_path)
        if stored.format == "parquet":
            with path.open("rb") as handle:
                self._client.raw_insert(loading, insert_block=handle.read() if path.stat().st_size < CHUNK_BYTES else _chunks(handle),
                                        fmt="Parquet")
            return
        if stored.format == "xlsx":
            header, rows = workbook_rows(path.open("rb"))
            block: bytes | Iterator[bytes] = _csv_chunks(header, rows)
            settings = {"input_format_csv_skip_first_lines": 1}
            self._client.raw_insert(loading, insert_block=block, fmt="CSV", settings=settings)
            return
        delimiter, _ = _read_csv_head(path)
        settings = {"input_format_csv_skip_first_lines": 1, "format_csv_delimiter": delimiter,
                    "input_format_csv_use_best_effort_in_schema_inference": 1}
        with path.open("rb") as handle:
            self._client.raw_insert(loading, insert_block=_chunks(handle, strip_bom=True), fmt="CSV", settings=settings)

    def reload(self, source_id: str) -> int:
        """Load the stored original again, with the confirmed column types; returns the rows loaded."""
        stored = self._store.file_of_source(source_id)
        if stored is None:
            raise UploadNotFound(f"source {source_id!r} has no stored file")
        table = Table(source_id)
        columns = [FileColumn(n, t) for n, t in stored.columns]
        return self._stream(Source(source_id, "file", (table,)), table, stored, columns)


def _chunks(handle: BinaryIO, strip_bom: bool = False) -> Iterator[bytes]:
    first = True
    while chunk := handle.read(CHUNK_BYTES):
        if first and strip_bom and chunk.startswith(b"\xef\xbb\xbf"):
            chunk = chunk[3:]
        first = False
        yield chunk


def _csv_chunks(header: list[str], rows: Iterator[list[str]]) -> Iterator[bytes]:
    buffer = StringIO()
    writer = csv.writer(buffer)
    writer.writerow(header)
    count = 0
    for row in rows:
        writer.writerow(row)
        count += 1
        if count % 5000 == 0:
            yield buffer.getvalue().encode("utf-8")
            buffer.seek(0)
            buffer.truncate()
    yield buffer.getvalue().encode("utf-8")
