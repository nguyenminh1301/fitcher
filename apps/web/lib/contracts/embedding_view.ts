// Generated from the backend Pydantic contract by npm run contracts:generate; do not edit.

export type Backend = "local" | "provider";
export type ProviderId = string | null;
export type Model = string;
export type Dimensions = number;
export type NeedsReindex = boolean;

export interface EmbeddingView {
  backend: Backend;
  provider_id: ProviderId;
  model: Model;
  dimensions: Dimensions;
  needs_reindex: NeedsReindex;
}
