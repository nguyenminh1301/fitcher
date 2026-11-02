// Generated from the backend Pydantic contract by npm run contracts:generate; do not edit.

export type Intent = "data_query";
/**
 * @minItems 1
 */
export type MetricIds = [string, ...string[]];
export type Dimensions = string[];
/**
 * @minItems 1
 */
export type Periods = [Period, ...Period[]];
export type Label = string;
export type Start = string;
export type End = string;
export type Column = string;
export type Op = "=" | "!=" | "<" | "<=" | ">" | ">=" | "in" | "not in";
export type Value = string | number | boolean | (string | number | boolean)[];
export type Filters = Filter[];
export type TopN = number | null;
export type RankBy = string | null;
export type RankPeriod = string | null;
export type Compare = boolean;
export type Dataset = string;
export type Warnings = string[];

export interface QuerySpec {
  intent?: Intent;
  metric_ids: MetricIds;
  dimensions?: Dimensions;
  periods: Periods;
  filters?: Filters;
  top_n?: TopN;
  rank_by?: RankBy;
  rank_period?: RankPeriod;
  compare?: Compare;
  dataset: Dataset;
  warnings?: Warnings;
}
/**
 * A labelled half-open date range ``[start, end)``.
 */
export interface Period {
  label: Label;
  start: Start;
  end: End;
}
export interface Filter {
  column: Column;
  op: Op;
  value: Value;
}
