// Generated from the backend Pydantic contract by npm run contracts:generate; do not edit.

export type Id = string;
export type Username = string;
export type DisplayName = string;
export type Roles = string[];
export type Enabled = boolean;

export interface UserView {
  id: Id;
  username: Username;
  display_name: DisplayName;
  roles: Roles;
  enabled: Enabled;
}
