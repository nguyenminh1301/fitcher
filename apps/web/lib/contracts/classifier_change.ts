// Generated from the backend Pydantic contract by npm run contracts:generate; do not edit.

export type Enabled = boolean;
export type Engine = "provider" | "local_onnx";
export type ProviderId = string | null;
export type Model = string | null;

export interface ClassifierChange {
  enabled: Enabled;
  engine?: Engine;
  provider_id?: ProviderId;
  model?: Model;
}
