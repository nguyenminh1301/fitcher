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

export interface SourceView {
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
