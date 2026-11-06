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
export type Name = string;
export type Kind = "node" | "llm" | "sql" | "access";
export type Status1 = "ok" | "err" | "deny";
export type Ms = number | null;
export type Meta = string[];
export type Sql = string | null;
export type Error1 = string | null;
export type Items = TraceItem[];

export interface RunTrace {
  run: RunRow;
  items: Items;
}
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
/**
 * One step of a run, in time order: a graph node, an LLM call, a SQL attempt or an access decision.
 */
export interface TraceItem {
  name: Name;
  kind: Kind;
  status: Status1;
  ms?: Ms;
  meta?: Meta;
  sql?: Sql;
  error?: Error1;
}
