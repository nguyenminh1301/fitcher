// Generated from the backend Pydantic contract by npm run contracts:generate; do not edit.

export type Id = string;
export type SourceId = string;
export type Tables = string[];
export type Status = "running" | "succeeded" | "failed";
export type Id1 = "marts" | "profile" | "files" | "draft" | "approve" | "compile" | "activate";
export type State = "pending" | "running" | "done" | "failed";
export type Done = number | null;
export type Total = number | null;
export type Steps = InstantStep[];
export type FailedStep = string | null;
export type Error = string | null;
export type Pack = string;
export type Datasets = number;
export type Relationships = number;
export type Skipped = string[];
export type Dropped = string[];
export type Slow = string[];
export type SuggestedQuestions = string[];
export type StartedAt = string;
export type FinishedAt = string | null;

export interface InstantJobReply {
  job: InstantJobView;
}
export interface InstantJobView {
  id: Id;
  source_id: SourceId;
  tables: Tables;
  status: Status;
  steps: Steps;
  failed_step?: FailedStep;
  error?: Error;
  result?: InstantResult | null;
  started_at: StartedAt;
  finished_at?: FinishedAt;
}
export interface InstantStep {
  id: Id1;
  state: State;
  done?: Done;
  total?: Total;
}
export interface InstantResult {
  pack: Pack;
  datasets?: Datasets;
  relationships?: Relationships;
  skipped?: Skipped;
  dropped?: Dropped;
  slow?: Slow;
  suggested_questions?: SuggestedQuestions;
}
