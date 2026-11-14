"""Data sources as the Sources page and the setup's Data step show and change them (DECISIONS §4, §15).

No contract carries a stored password: ``password`` appears only in what the page sends when it connects a source
or replaces the password, and every response omits it. Sizes and row counts are estimates from the source's own
statistics and are labelled approximate.
"""

from datetime import datetime
from typing import Literal

from pydantic import Field

from app.contracts.query_spec import ContractModel

SourceKind = Literal["postgres", "mysql", "sqlserver", "file"]
Mode = Literal["live", "copy"]
TlsMode = Literal["prefer", "require", "verify"]
FailureReason = Literal["unreachable", "refused", "authentication", "tls", "database_not_found", "permission", "unknown",
                        "interrupted"]


class SourceConnection(ContractModel):
    """The connection fields of a PostgreSQL or MySQL/MariaDB source."""

    kind: Literal["postgres", "mysql", "sqlserver"]
    host: str = Field(max_length=255)
    port: int | None = Field(default=None, ge=1, le=65535)
    database: str = Field(max_length=255)
    # PostgreSQL ("public") and SQL Server ("dbo") only; the default when empty.
    schema_name: str | None = Field(default=None, max_length=255)
    user: str = Field(max_length=255)
    password: str = Field(max_length=1024, repr=False)
    # "prefer" when absent, except for SQL Server, whose connection requires encryption by default.
    tls_mode: TlsMode | None = None
    ca_certificate: str | None = Field(default=None, max_length=20_000)


class SourceCreate(SourceConnection):
    # The name of the source: `src_<name>` and `raw.<name>__<table>` in ClickHouse.
    name: str = Field(max_length=40)


class SourcePatch(ContractModel):
    host: str | None = Field(default=None, max_length=255)
    port: int | None = Field(default=None, ge=1, le=65535)
    database: str | None = Field(default=None, max_length=255)
    schema_name: str | None = Field(default=None, max_length=255)
    user: str | None = Field(default=None, max_length=255)
    # A new password replaces the stored one once the connection works with it; absent keeps the stored one.
    password: str | None = Field(default=None, max_length=1024, repr=False)
    tls_mode: TlsMode | None = None
    # A new certificate replaces the stored one; an empty string removes it.
    ca_certificate: str | None = Field(default=None, max_length=20_000)


class ColumnView(ContractModel):
    name: str
    type: str
    nullable: bool


class ForeignKeyView(ContractModel):
    columns: list[str]
    ref_table: str
    ref_columns: list[str]


class TableView(ContractModel):
    name: str
    kind: Literal["table", "view"]
    # Estimates from the source's statistics; null when the source reports none.
    rows: int | None
    size_bytes: int | None
    columns: list[ColumnView]
    primary_key: list[str]
    foreign_keys: list[ForeignKeyView]
    # Columns ClickHouse reads as strings (arrays, JSON, enums, geometry); the list marks them.
    unusual_columns: list[str]
    selected: bool
    mode: Mode
    proposed_mode: Mode
    # small, unknown_size, rows, size or view.
    reason: str
    # A live table tied by a foreign key to another live table: joining them reads both over the network.
    slow: bool
    interval_seconds: int
    cursor_column: str | None
    # Columns an incremental copy can follow: numbers and dates.
    cursor_candidates: list[str]
    last_synced_at: datetime | None
    last_rows: int | None
    next_run_at: datetime | None


class ProbeResult(ContractModel):
    tables: list[TableView]


class SyncView(ContractModel):
    id: int
    status: Literal["running", "succeeded", "failed", "cancelled"]
    started_by: Literal["manual", "schedule", "setup"]
    started_at: datetime
    finished_at: datetime | None
    # One entry per table: {"table", "mode", "rows", "full"}.
    results: list[dict]
    error: FailureReason | None


class SourceView(ContractModel):
    id: str
    kind: SourceKind
    host: str | None
    port: int | None
    database: str | None
    schema_name: str | None
    user: str | None
    tls_mode: TlsMode
    has_ca: bool
    created_at: datetime
    table_count: int
    selected_count: int
    last_sync: SyncView | None


class SourceDetail(SourceView):
    tables: list[TableView]


class TableChangeInput(ContractModel):
    name: str
    selected: bool | None = None
    mode: Mode | None = None
    interval_seconds: int | None = Field(default=None, ge=60, le=31_536_000)
    # Absent keeps the cursor, null clears it and a column name sets it.
    cursor_column: str | None = None


class TablesChange(ContractModel):
    tables: list[TableChangeInput] = Field(max_length=5000)


class FileColumn(ContractModel):
    name: str
    type: str


class FileUploadView(ContractModel):
    id: str
    file_name: str
    format: Literal["csv", "xlsx", "parquet"]
    size_bytes: int
    # The types ClickHouse inferred from a sample, to be confirmed or changed before the load.
    columns: list[FileColumn]
    # The first rows of the file as text, so the page can show what the types describe.
    sample: list[list[str | None]]


class FileLoad(ContractModel):
    # The source (and its table) is named after the file unless a name is given.
    name: str | None = Field(default=None, max_length=40)
    columns: list[FileColumn]
