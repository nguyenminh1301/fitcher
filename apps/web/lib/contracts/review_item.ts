// Generated from the backend Pydantic contract by npm run contracts:generate; do not edit.

export type Id = string;
export type File = string;
export type Name = string;
export type Kind = "item";
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
