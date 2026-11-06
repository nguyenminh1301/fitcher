// Generated from the backend Pydantic contract by npm run contracts:generate; do not edit.

export type Id = string;
export type Ts = string;
export type Passed = boolean;
export type Threshold = number;
export type Passed1 = number;
export type Failed = number;
export type NotScored = number;
export type CaseId = string;
export type Category = string;
export type Reason = string;
export type FailedCases = FailedCase[];
export type Regressed = boolean | null;

export interface EvalReportView {
  id: Id;
  ts: Ts;
  passed: Passed;
  threshold: Threshold;
  layers: Layers;
  categories: Categories;
  failed_cases: FailedCases;
  regressed?: Regressed;
}
export interface Layers {
  [k: string]: EvalLayer;
}
export interface EvalLayer {
  passed: Passed1;
  failed: Failed;
  not_scored: NotScored;
}
export interface Categories {
  [k: string]: string;
}
export interface FailedCase {
  case_id: CaseId;
  category: Category;
  reason: Reason;
}
