"""Uploaded CSV, XLSX and Parquet files become ``raw`` tables with column types the user confirmed (DECISIONS §4)."""

from io import BytesIO
import zipfile

from openpyxl import Workbook
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from sources_fixtures import UploadClickHouse
from state_fixtures import new_state

from app.onboarding.docs_parser import DocumentRejected
from app.sources import files
from app.sources.files import FileColumn, FileService, FileTooLarge
from app.sources.store import DuplicateSource, SourceStore

CSV = "Mã đơn,Số tiền,Ngày\nA1,10.5,2024-01-02\nA2,3,2024-01-03\n".encode()


@pytest.fixture
def parts(tmp_path):
    db, _ = new_state(tmp_path)
    store, clickhouse = SourceStore(db), UploadClickHouse()
    return store, clickhouse, FileService(store, clickhouse, tmp_path / "uploads", max_bytes=1024 * 1024)


def workbook(rows, macro=False) -> bytes:
    book = Workbook()
    sheet = book.active
    for row in rows:
        sheet.append(row)
    buffer = BytesIO()
    book.save(buffer)
    data = buffer.getvalue()
    if not macro:
        return data
    source, target = zipfile.ZipFile(BytesIO(data)), BytesIO()
    with zipfile.ZipFile(target, "w") as archive:
        for name in source.namelist():
            archive.writestr(name, source.read(name))
        archive.writestr("xl/vbaProject.bin", b"x")
    return target.getvalue()


def parquet() -> bytes:
    buffer = BytesIO()
    pq.write_table(pa.table({"id": pa.array([1, 2], pa.int64()), "name": ["a", "b"], "at": pa.array([1, 2], pa.timestamp("us"))}),
                   buffer)
    return buffer.getvalue()


# Type from the content


@pytest.mark.parametrize(("data", "name", "kind"), [
    (CSV, "orders.csv", "csv"), (CSV, "orders.xlsx", "csv"), (parquet(), "a.csv", "parquet"),
    (workbook([["a"], [1]]), "a.csv", "xlsx"), (b"\xef\xbb\xbfa;b\n1;2\n", "x.txt", "csv"),
])
def test_the_type_comes_from_the_content_not_the_name(data, name, kind):
    assert files.detect_format(data, name) == kind


@pytest.mark.parametrize(("data", "status"), [
    (b"", 422), (b"%PDF-1.7 x", 415), (b"\x00\x01\x02binary", 415), (b"\xff\xfe bad utf8 \xc3(", 422),
    (workbook([["a"]], macro=True), 415), (b"PK\x03\x04 not a zip", 415),
])
def test_content_that_is_not_a_supported_table_is_rejected(data, status):
    with pytest.raises(DocumentRejected) as raised:
        files.detect_format(data, "x")
    assert raised.value.status == status


def test_a_macro_enabled_workbook_is_rejected_by_the_document_readers_rule():
    with pytest.raises(DocumentRejected, match="macro"):
        files.detect_format(workbook([["a"]], macro=True), "book.xlsx")


# Names


@pytest.mark.parametrize(("file_name", "table"), [
    ("Orders 2024.csv", "orders_2024"), ("Đơn hàng.xlsx", "don_hang"), ("2024-sales.parquet", "f_2024_sales"),
    ("....csv", "data"), ("x" * 80 + ".csv", "x" * 40),
])
def test_a_file_name_becomes_a_table_name(file_name, table):
    assert files.table_name(file_name) == table


def test_header_names_are_trimmed_filled_in_and_made_unique():
    assert files.normalize_header([" id ", "", "id", "Tên", "id"]) == ["id", "column_2", "id_2", "Tên", "id_3"]


@pytest.mark.parametrize("type_name", ["String", "Nullable(Int64)", "Float64", "Date", "DateTime64(6)",
                                       "DateTime64(6, 'UTC')", "Decimal(18, 4)", "Nullable(Bool)", "UInt8"])
def test_allowed_column_types_pass(type_name):
    files.check_columns([FileColumn("a", type_name)])


@pytest.mark.parametrize("type_name", ["String) ENGINE = Memory --", "Array(String)", "Nullable(Nullable(String))", "",
                                       "Int64; DROP TABLE x", "Enum8('a'=1)"])
def test_a_column_type_outside_the_allowed_set_is_refused_before_it_reaches_ddl(type_name):
    with pytest.raises(ValueError, match="type"):
        files.check_columns([FileColumn("a", type_name)])


def test_columns_need_names_that_are_present_and_unique():
    with pytest.raises(ValueError, match="unique"):
        files.check_columns([FileColumn("a", "String"), FileColumn("a", "Int64")])
    with pytest.raises(ValueError, match="name"):
        files.check_columns([FileColumn("", "String")])
    with pytest.raises(ValueError, match="column"):
        files.check_columns([])


# Conversion


def test_a_workbook_becomes_csv_rows_with_the_first_non_empty_row_as_header():
    import datetime

    data = workbook([[None, None], ["id", "when", "note"], [1, datetime.date(2024, 1, 2), "a,b"], [2, None, None]])

    header, rows = files.workbook_rows(data)

    assert header == ["id", "when", "note"]
    assert list(rows) == [["1", "2024-01-02", "a,b"], ["2", "", ""]]


def test_a_parquet_schema_maps_to_clickhouse_types():
    assert files.parquet_columns(parquet()) == [
        FileColumn("id", "Nullable(Int64)"), FileColumn("name", "Nullable(String)"),
        FileColumn("at", "Nullable(DateTime64(6))")]


# Upload


def test_an_upload_keeps_the_original_and_proposes_the_inferred_types(parts, tmp_path):
    store, clickhouse, service = parts

    upload = service.upload("Orders.csv", BytesIO(CSV), uploaded_by="lab.admin")

    assert (upload.format, upload.size_bytes, upload.file_name) == ("csv", len(CSV), "Orders.csv")
    assert [(c.name, c.type) for c in upload.columns] == [
        ("Mã đơn", "Nullable(String)"), ("Số tiền", "Nullable(Float64)"), ("Ngày", "Nullable(Date)")]
    assert upload.sample == [["A1", "10.5", "2024-01-02"], ["A2", "3", "2024-01-03"]]
    [stored] = [p for p in (tmp_path / "uploads").rglob("*") if p.is_file()]
    assert stored.read_bytes() == CSV
    describe = next(sql for sql in clickhouse.sql if sql.startswith("DESCRIBE"))
    assert describe == "DESCRIBE TABLE format(CSVWithNames, {sample:String})"
    assert clickhouse.parameters["sample"].startswith("Mã đơn,Số tiền,Ngày\nA1,")


def test_a_semicolon_file_is_read_with_that_delimiter(parts):
    _, clickhouse, service = parts

    service.upload("a.csv", BytesIO(b"a;b\n1;2\n"), uploaded_by=None)

    assert clickhouse.query_settings["format_csv_delimiter"] == ";"


def test_an_upload_above_the_size_cap_is_refused_and_leaves_no_file(parts, tmp_path):
    _, _, service = parts

    with pytest.raises(FileTooLarge):
        service.upload("big.csv", BytesIO(b"a\n" + b"1\n" * (1024 * 1024)), uploaded_by=None)

    assert list((tmp_path / "uploads").rglob("*")) == [] or all(p.is_dir() for p in (tmp_path / "uploads").rglob("*"))


def test_a_rejected_file_leaves_nothing_behind(parts, tmp_path):
    _, _, service = parts

    with pytest.raises(DocumentRejected):
        service.upload("x.csv", BytesIO(b"\x00\x01"), uploaded_by=None)

    assert not any(p.is_file() for p in (tmp_path / "uploads").rglob("*"))


def test_an_xlsx_upload_is_inferred_from_a_csv_rendering_of_its_first_sheet(parts):
    _, clickhouse, service = parts

    upload = service.upload("book.xlsx", BytesIO(workbook([["id", "name"], [1, "a"], [2, "b"]])), uploaded_by=None)

    assert upload.format == "xlsx" and upload.sample == [["1", "a"], ["2", "b"]]
    assert clickhouse.parameters["sample"] == "id,name\n1,a\n2,b\n"


def test_a_parquet_upload_takes_its_types_from_the_file(parts):
    _, clickhouse, service = parts

    upload = service.upload("t.parquet", BytesIO(parquet()), uploaded_by=None)

    assert upload.format == "parquet" and [c.type for c in upload.columns][0] == "Nullable(Int64)"
    assert not any(sql.startswith("DESCRIBE") for sql in clickhouse.sql)


# Load


def confirmed(upload, **changes):
    return [FileColumn(c.name, changes.get(c.name, c.type)) for c in upload.columns]


def test_a_confirmed_load_stages_streams_publishes_and_registers_the_source(parts):
    store, clickhouse, service = parts
    upload = service.upload("Orders.csv", BytesIO(CSV), uploaded_by="lab.admin")

    source = service.load(upload.id, None, confirmed(upload, **{"Số tiền": "Nullable(Decimal(18, 2))"}))

    assert (source.id, source.kind) == ("orders", "file")
    create = next(sql for sql in clickhouse.sql if sql.startswith("CREATE TABLE `raw`.`orders__orders__loading`"))
    assert create == ("CREATE TABLE `raw`.`orders__orders__loading` (`Mã đơn` Nullable(String), "
                      "`Số tiền` Nullable(Decimal(18, 2)), `Ngày` Nullable(Date)) ENGINE = MergeTree ORDER BY tuple()")
    table, fmt, settings, data = clickhouse.inserted[0]
    assert (table, fmt) == ("`raw`.`orders__orders__loading`", "CSV")
    assert settings["input_format_csv_skip_first_lines"] == 1 and data == CSV
    assert clickhouse.raw["orders__orders"] == 2
    [table_row] = store.tables("orders")
    assert (table_row.name, table_row.selected, table_row.mode, table_row.last_rows) == ("orders", True, "copy", 2)
    assert store.syncs("orders")[0].status == "succeeded"
    assert store.get_file(upload.id).source_id == "orders"


def test_the_source_can_be_named_and_a_taken_name_is_a_conflict(parts):
    store, _, service = parts
    first = service.upload("a.csv", BytesIO(CSV), uploaded_by=None)
    second = service.upload("b.csv", BytesIO(CSV), uploaded_by=None)
    service.load(first.id, "sales_2024", confirmed(first))

    with pytest.raises(DuplicateSource):
        service.load(second.id, "sales_2024", confirmed(second))
    assert [s.id for s in store.list()] == ["sales_2024"]


def test_a_failed_load_publishes_nothing_and_registers_no_source(parts):
    store, clickhouse, service = parts
    upload = service.upload("a.csv", BytesIO(CSV), uploaded_by=None)
    clickhouse.fail_on = "raw_insert"
    clickhouse.error = RuntimeError("Cannot parse input: expected ',' before: 'x'")

    with pytest.raises(files.LoadFailed):
        service.load(upload.id, None, confirmed(upload))

    assert store.list() == [] and "a__a" not in clickhouse.raw and "a__a__loading" not in clickhouse.raw


def test_a_load_with_a_column_set_that_differs_from_the_upload_is_refused(parts):
    _, _, service = parts
    upload = service.upload("a.csv", BytesIO(CSV), uploaded_by=None)

    with pytest.raises(ValueError, match="columns"):
        service.load(upload.id, None, [FileColumn("other", "String")])


def test_an_xlsx_is_loaded_as_csv_rows_and_a_parquet_file_as_itself(parts):
    _, clickhouse, service = parts
    clickhouse.inferred = [("id", "Nullable(Int64)"), ("name", "Nullable(String)")]
    book = service.upload("book.xlsx", BytesIO(workbook([["id", "name"], [1, "a"]])), uploaded_by=None)
    service.load(book.id, None, [FileColumn("id", "Nullable(Int64)"), FileColumn("name", "Nullable(String)")])
    assert clickhouse.inserted[0][1:2] == ("CSV",) and clickhouse.inserted[0][3] == b"id,name\r\n1,a\r\n"

    data = parquet()
    table = service.upload("t.parquet", BytesIO(data), uploaded_by=None)
    service.load(table.id, None, [FileColumn(c.name, c.type) for c in table.columns])
    assert clickhouse.inserted[1][1] == "Parquet" and clickhouse.inserted[1][3] == data


def test_a_file_source_is_reloaded_from_its_stored_original(parts):
    store, clickhouse, service = parts
    upload = service.upload("a.csv", BytesIO(CSV), uploaded_by=None)
    service.load(upload.id, None, confirmed(upload))
    clickhouse.inserted.clear()

    rows = service.reload("a")

    assert rows == 2 and clickhouse.inserted[0][3] == CSV
    assert any(sql.startswith("EXCHANGE TABLES") for sql in clickhouse.sql)


def test_an_unknown_upload_is_not_found(parts):
    _, _, service = parts

    with pytest.raises(files.UploadNotFound):
        service.load("missing", None, [FileColumn("a", "String")])
