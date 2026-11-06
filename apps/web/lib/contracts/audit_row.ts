// Generated from the backend Pydantic contract by npm run contracts:generate; do not edit.

export type Ts = string;
export type TraceId = string;
export type UserId = string;
export type Role = string;
export type Decision = "ALLOW" | "DENY";
export type Dataset = string;
export type BlockedTables = string[];
export type Reason = string;

export interface AuditRow {
  ts: Ts;
  trace_id: TraceId;
  user_id: UserId;
  role: Role;
  decision: Decision;
  dataset: Dataset;
  blocked_tables: BlockedTables;
  reason: Reason;
}
