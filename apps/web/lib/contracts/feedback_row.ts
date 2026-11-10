// Generated from the backend Pydantic contract by npm run contracts:generate; do not edit.

export type TraceId = string;
export type Ts = string;
export type UserId = string;
export type Rating = "like" | "dislike";
export type Question = string;
export type Note = string | null;
export type RunStatus = string;
export type Proposal = ("proposed" | "approved" | "dismissed") | null;

export interface FeedbackRow {
  trace_id: TraceId;
  ts: Ts;
  user_id: UserId;
  rating: Rating;
  question: Question;
  note?: Note;
  run_status: RunStatus;
  proposal?: Proposal;
}
