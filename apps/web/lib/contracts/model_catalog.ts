// Generated from the backend Pydantic contract by npm run contracts:generate; do not edit.

export type ProviderId = string;
export type Id = string;
export type ProviderId1 = string;
export type Kind = "chat" | "embedding" | "other";
export type Free = "none" | "free" | "free_tier";
export type InputPrice = number | null;
export type OutputPrice = number | null;
export type Context = number | null;
export type StructuredOutput = boolean | null;
export type Benchmark = number | null;
export type MedianLatencyMs = number | null;
export type Models = CatalogEntry[];

export interface ModelCatalog {
  provider_id: ProviderId;
  models: Models;
}
/**
 * One model of a provider with what it is for, its price, limits and measured speed (``app/llm/catalog.py``).
 */
export interface CatalogEntry {
  id: Id;
  provider_id: ProviderId1;
  kind: Kind;
  free: Free;
  input_price: InputPrice;
  output_price: OutputPrice;
  context: Context;
  structured_output: StructuredOutput;
  benchmark: Benchmark;
  median_latency_ms: MedianLatencyMs;
}
