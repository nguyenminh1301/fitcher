// Generated from the backend Pydantic contract by npm run contracts:generate; do not edit.

export type PromptTokens = number;
export type Datasets = number;
export type ModelMissing = string | null;

export interface InstantEstimate {
  prompt_tokens: PromptTokens;
  datasets: Datasets;
  model_missing?: ModelMissing;
}
