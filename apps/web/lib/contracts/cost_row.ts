// Generated from the backend Pydantic contract by npm run contracts:generate; do not edit.

export type Day = string;
export type Alias = string;
export type Model = string;
export type Tier = string;
export type Provider = string;
export type Calls = number;
export type CostUsd = number;

/**
 * Estimated LLM cost of one day, provider, model and tier, from the LiteLLM SDK's price table.
 */
export interface CostRow {
  day: Day;
  alias: Alias;
  model: Model;
  tier: Tier;
  provider: Provider;
  calls: Calls;
  cost_usd: CostUsd;
}
