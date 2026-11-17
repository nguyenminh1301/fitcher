// Generated from the backend Pydantic contract by npm run contracts:generate; do not edit.

export type Id = string;
export type State = "pending" | "done" | "skipped";
export type Steps = SetupStep[];
export type Complete = boolean;

export interface SetupStatus {
  steps: Steps;
  complete: Complete;
}
export interface SetupStep {
  id: Id;
  state: State;
}
