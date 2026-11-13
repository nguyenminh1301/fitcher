// Generated from the backend Pydantic contract by npm run contracts:generate; do not edit.

export type Backend = "local" | "provider";
export type Model = string;
export type ProviderId = string | null;
export type Dimensions = number | null;
export type ConfirmReindex = boolean;

export interface EmbeddingChange {
  backend: Backend;
  model: Model;
  provider_id?: ProviderId;
  dimensions?: Dimensions;
  confirm_reindex?: ConfirmReindex;
}
