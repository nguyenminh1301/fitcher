// Generated from the backend Pydantic contract by npm run contracts:generate; do not edit.

export type ProviderId = string;
export type Models = string[];
export type Model = string | null;
export type StructuredOutput = boolean;
export type Paid = boolean;
export type Error = string | null;

export interface ProviderTestResult {
  provider_id: ProviderId;
  models: Models;
  model: Model;
  structured_output: StructuredOutput;
  paid: Paid;
  error: Error;
}
