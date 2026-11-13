// Generated from the backend Pydantic contract by npm run contracts:generate; do not edit.

export type Tier = string;
export type ProviderId = string | null;
export type Model = string | null;
export type Evaluated = boolean;
export type Passed = boolean;
export type Reason = string;
export type ReportId = string | null;
export type ReportTs = string | null;

export interface TierView {
  tier: Tier;
  provider_id: ProviderId;
  model: Model;
  eval?: EvalStatus | null;
}
/**
 * The latest eval report of the active pack that ran the tier on this model; it informs and never gates.
 */
export interface EvalStatus {
  evaluated: Evaluated;
  passed: Passed;
  reason: Reason;
  report_id?: ReportId;
  report_ts?: ReportTs;
}
