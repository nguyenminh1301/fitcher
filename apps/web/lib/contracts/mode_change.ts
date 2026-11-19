// Generated from the backend Pydantic contract by npm run contracts:generate; do not edit.

export type Mode = "auto_free" | "auto_best" | "manual";

export interface ModeChange {
  mode: Mode;
}
