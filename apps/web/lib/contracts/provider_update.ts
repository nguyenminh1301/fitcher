// Generated from the backend Pydantic contract by npm run contracts:generate; do not edit.

export type Name = string | null;
export type ApiKey = string | null;
export type BaseUrl = string | null;

export interface ProviderUpdate {
  name?: Name;
  api_key?: ApiKey;
  base_url?: BaseUrl;
}
