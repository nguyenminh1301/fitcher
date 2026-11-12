// Generated from the backend Pydantic contract by npm run contracts:generate; do not edit.

export type Body = string | null;
export type Formula = string | null;
/**
 * @minItems 1
 */
export type MetricIds = [string, ...string[]];
export type Dataset = string;
export type Dimensions = string[];
export type Column = string;
export type Op = "=" | "!=" | "in" | "not in";
/**
 * @minItems 1
 */
export type Values = [string | number | number | boolean, ...(string | number | number | boolean)[]];
export type Filters = SpecFilter[];
export type TopN = number | null;
export type RankBy = string | null;
export type SpecReviewed = boolean | null;

export interface ReviewItemPatch {
  body?: Body;
  formula?: Formula;
  spec?: ReviewedSpec | null;
  spec_reviewed?: SpecReviewed;
}
/**
 * The QuerySpec a proposal's example settles for its question, without periods (DECISIONS §6 step 7).
 */
export interface ReviewedSpec {
  metric_ids: MetricIds;
  dataset: Dataset;
  dimensions?: Dimensions;
  filters?: Filters;
  top_n?: TopN;
  rank_by?: RankBy;
}
export interface SpecFilter {
  column: Column;
  op: Op;
  values: Values;
}
