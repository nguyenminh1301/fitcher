// Generated from the backend Pydantic contract by npm run contracts:generate; do not edit.

export type ApiKey = string;
export type Label = string;

export interface ProviderKeyCreate {
  api_key: ApiKey;
  label?: Label;
}
