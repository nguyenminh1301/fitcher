// Generated from the backend Pydantic contract by npm run contracts:generate; do not edit.

export type DisplayName = string | null;
export type Roles = string[] | null;
export type Enabled = boolean | null;

export interface UserChange {
  display_name?: DisplayName;
  roles?: Roles;
  enabled?: Enabled;
}
