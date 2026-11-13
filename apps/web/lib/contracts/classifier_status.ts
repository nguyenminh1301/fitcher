// Generated from the backend Pydantic contract by npm run contracts:generate; do not edit.

export type Enabled = boolean;
export type ModelPresent = boolean;
export type Version = string | null;

export interface ClassifierStatus {
  enabled: Enabled;
  model_present: ModelPresent;
  version: Version;
}
