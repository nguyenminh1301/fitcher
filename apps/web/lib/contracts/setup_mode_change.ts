// Generated from the backend Pydantic contract by npm run contracts:generate; do not edit.

export type Mode = "individual" | "team";
export type Email = string;
export type DisplayName = string;
export type Password = string;

export interface SetupModeChange {
  mode: Mode;
  admin?: FirstAdminInput | null;
}
export interface FirstAdminInput {
  email: Email;
  display_name: DisplayName;
  password: Password;
}
