// Generated from the backend Pydantic contract by npm run contracts:generate; do not edit.

export type Id = string;
export type File = string;
export type Name = string;
export type Kind = "item" | "proposal";
export type Status = "draft" | "approved";
export type Confidence = number;
export type Body = string;
export type Formula = string | null;
export type Source = string;
export type Quote = string | null;
export type Deleted = boolean;
export type Kind1 = "manual" | "profile" | "doc" | "error" | "trace";
export type Ref = string;
export type EvidenceRefs = EvidenceRef[];
/**
 * @minItems 1
 */
export type Columns = [ColumnInfo, ...ColumnInfo[]];
export type Name1 = string;
export type Type = "string" | "number" | "date" | "datetime" | "boolean";
export type Role = "dimension" | "measure" | "time";
export type Format = ("currency" | "count" | "ratio" | "percent" | "days" | "number") | null;
/**
 * @maxItems 5000
 */
export type Rows = (string | number | boolean | null)[][];
export type RowCount = number;
export type Truncated = boolean;
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
export type SpecReviewed = boolean;

export interface ReviewItem {
  id: Id;
  file: File;
  name: Name;
  kind: Kind;
  status: Status;
  confidence: Confidence;
  body: Body;
  formula?: Formula;
  evidence?: ReviewEvidence | null;
  evidence_refs?: EvidenceRefs;
  test_result?: Result | null;
  spec?: ReviewedSpec | null;
  spec_reviewed?: SpecReviewed;
}
/**
 * The evidence shown first: a cited document, else the first entry.
 */
export interface ReviewEvidence {
  source: Source;
  quote?: Quote;
  deleted?: Deleted;
}
export interface EvidenceRef {
  kind: Kind1;
  ref: Ref;
}
export interface Result {
  columns: Columns;
  rows: Rows;
  row_count: RowCount;
  truncated?: Truncated;
}
export interface ColumnInfo {
  name: Name1;
  type: Type;
  role: Role;
  format?: Format;
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
