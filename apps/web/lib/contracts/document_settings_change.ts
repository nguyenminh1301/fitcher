// Generated from the backend Pydantic contract by npm run contracts:generate; do not edit.

export type Enabled = boolean;
export type Confirm = boolean;

export interface DocumentSettingsChange {
  enabled: Enabled;
  confirm?: Confirm;
}
