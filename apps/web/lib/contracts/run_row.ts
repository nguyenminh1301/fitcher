// Generated from the backend Pydantic contract by npm run contracts:generate; do not edit.

export type TraceId = string;
export type Ts = string;
export type UserId = string;
export type Role = string;
export type Question = string;
export type Intent = string;
export type Status = string;
export type LatencyMs = number;
export type CostUsd = number;
export type Error = string;

export interface RunRow {
  trace_id: TraceId;
  ts: Ts;
  user_id: UserId;
  role: Role;
  question: Question;
  intent: Intent;
  status: Status;
  latency_ms: LatencyMs;
  cost_usd: CostUsd;
  error?: Error;
}
