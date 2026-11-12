// Generated from the backend Pydantic contract by npm run contracts:generate; do not edit.

export type Pack = string;
export type Running = boolean;

export interface EvalRunStarted {
  pack: Pack;
  running: Running;
}
