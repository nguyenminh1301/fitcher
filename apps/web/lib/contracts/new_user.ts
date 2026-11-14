// Generated from the backend Pydantic contract by npm run contracts:generate; do not edit.

export type Email = string;
export type DisplayName = string;
export type Password = string;
export type Roles = string[];

export interface NewUser {
  email: Email;
  display_name: DisplayName;
  password: Password;
  roles: Roles;
}
