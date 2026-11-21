// Generated from the backend Pydantic contract by npm run contracts:generate; do not edit.

export type Ts = string;
export type TraceId = string;
export type UserId = string;
export type Source = string;
export type Verdict = string;
export type Mode = string;
export type Score = number | null;
export type RuleHits = string[];

export interface ScreeningRow {
  ts: Ts;
  trace_id: TraceId;
  user_id: UserId;
  source: Source;
  verdict: Verdict;
  mode: Mode;
  score: Score;
  rule_hits: RuleHits;
}
