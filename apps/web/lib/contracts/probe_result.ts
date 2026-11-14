// Generated from the backend Pydantic contract by npm run contracts:generate; do not edit.

export type Name = string;
export type Kind = "table" | "view";
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

export interface ProbeResult {
  tables: Tables;
}
export interface TableView {
  name: Name;
  kind: Kind;
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
