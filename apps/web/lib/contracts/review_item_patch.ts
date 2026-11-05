// Generated from the backend Pydantic contract by npm run contracts:generate; do not edit.

export type Body = string | null;
export type Formula = string | null;

export interface ReviewItemPatch {
  body?: Body;
  formula?: Formula;
}
