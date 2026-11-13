// Generated from the backend Pydantic contract by npm run contracts:generate; do not edit.

export type ProviderId = string;
export type Model = string;

export interface TierChange {
  provider_id: ProviderId;
  model: Model;
}
