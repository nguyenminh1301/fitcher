// Generated from the backend Pydantic contract by npm run contracts:generate; do not edit.

export type TraceId = string;
export type Rating = "like" | "dislike";
export type Note = string;

export interface FeedbackInput {
  trace_id: TraceId;
  rating: Rating;
  note?: Note;
}
