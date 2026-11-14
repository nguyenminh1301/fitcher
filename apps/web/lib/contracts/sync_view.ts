// Generated from the backend Pydantic contract by npm run contracts:generate; do not edit.

export type Id = number;
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

export interface SyncView {
  id: Id;
  status: Status;
  started_by: StartedBy;
  started_at: StartedAt;
  finished_at: FinishedAt;
  results: Results;
  error: Error;
}
