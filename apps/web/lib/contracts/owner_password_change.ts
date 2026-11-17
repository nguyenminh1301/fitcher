// Generated from the backend Pydantic contract by npm run contracts:generate; do not edit.

export type CurrentPassword = string | null;
export type NewPassword = string;

export interface OwnerPasswordChange {
  current_password?: CurrentPassword;
  new_password: NewPassword;
}
