// Generated from the backend Pydantic contract by npm run contracts:generate; do not edit.

export type Id = string;
export type Kind = "postgres" | "mysql" | "file";
export type Host = string | null;
export type Port = number | null;
export type Database = string | null;
export type SchemaName = string | null;
export type User = string | null;
export type TlsMode = "prefer" | "require" | "verify";
export type HasCa = boolean;
export type CreatedAt = string;
export type TableCount = number;
export type SelectedCount = number;
export type Id1 = number;
export type Status = "running" | "succeeded" | "failed" | "cancelled";
export type StartedBy = "manual" | "schedule" | "setup";
export type StartedAt = string;
export type FinishedAt = string | null;
export type Results = {
  [k: string]: unknown;
}[];
export type Error =
  | (
      | "unreachable"
      | "refused"
      | "authentication"
      | "tls"
      | "database_not_found"
      | "permission"
      | "unknown"
      | "interrupted"
    )
  | null;
export type Name = string;
export type Kind1 = "table" | "view";
export type Rows = number | null;
export type SizeBytes = number | null;
export type Name1 = string;
export type Type = string;
export type Nullable = boolean;
export type Columns = ColumnView[];
export type PrimaryKey = string[];
export type Columns1 = string[];
export type RefTable = string;
export type RefColumns = string[];
export type ForeignKeys = ForeignKeyView[];
export type UnusualColumns = string[];
export type Selected = boolean;
export type Mode = "live" | "copy";
export type ProposedMode = "live" | "copy";
export type Reason = string;
export type Slow = boolean;
export type IntervalSeconds = number;
export type CursorColumn = string | null;
export type CursorCandidates = string[];
export type LastSyncedAt = string | null;
export type LastRows = number | null;
export type NextRunAt = string | null;
export type Tables = TableView[];

export interface SourceDetail {
  id: Id;
  kind: Kind;
  host: Host;
  port: Port;
  database: Database;
  schema_name: SchemaName;
  user: User;
  tls_mode: TlsMode;
  has_ca: HasCa;
  created_at: CreatedAt;
  table_count: TableCount;
  selected_count: SelectedCount;
  last_sync: SyncView | null;
  tables: Tables;
}
export interface SyncView {
  id: Id1;
  status: Status;
  started_by: StartedBy;
  started_at: StartedAt;
  finished_at: FinishedAt;
  results: Results;
  error: Error;
}
export interface TableView {
  name: Name;
  kind: Kind1;
  rows: Rows;
  size_bytes: SizeBytes;
  columns: Columns;
  primary_key: PrimaryKey;
  foreign_keys: ForeignKeys;
  unusual_columns: UnusualColumns;
  selected: Selected;
  mode: Mode;
  proposed_mode: ProposedMode;
  reason: Reason;
  slow: Slow;
  interval_seconds: IntervalSeconds;
  cursor_column: CursorColumn;
  cursor_candidates: CursorCandidates;
  last_synced_at: LastSyncedAt;
  last_rows: LastRows;
  next_run_at: NextRunAt;
}
export interface ColumnView {
  name: Name1;
  type: Type;
  nullable: Nullable;
}
export interface ForeignKeyView {
  columns: Columns1;
  ref_table: RefTable;
  ref_columns: RefColumns;
}
