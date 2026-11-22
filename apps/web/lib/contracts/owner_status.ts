// Generated from the backend Pydantic contract by npm run contracts:generate; do not edit.

export type PasswordSet = boolean;
export type SignedIn = boolean;
export type Exposed = boolean;

export interface OwnerStatus {
  password_set: PasswordSet;
  signed_in: SignedIn;
  exposed: Exposed;
}
