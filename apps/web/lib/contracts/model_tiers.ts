// Generated from the backend Pydantic contract by npm run contracts:generate; do not edit.

export type Pack = string;
export type Tier = string;
export type Alias = string;
export type Provider = string;
export type DefaultAlias = string;
export type Editable = boolean;
export type Eligible = boolean;
export type Reason = string;
export type ReportId = string | null;
export type ReportTs = string | null;
export type Alias1 = string;
export type Provider1 = string;
export type Eligible1 = boolean;
export type Reason1 = string;
export type ReportId1 = string | null;
export type ReportTs1 = string | null;
export type Options = AliasOption[];
export type Tiers = ModelTier[];
export type CatalogError = string | null;

export interface ModelTiers {
  pack: Pack;
  tiers: Tiers;
  catalog_error?: CatalogError;
}
export interface ModelTier {
  tier: Tier;
  alias: Alias;
  provider: Provider;
  default_alias: DefaultAlias;
  editable: Editable;
  eligible: Eligible;
  reason: Reason;
  report_id?: ReportId;
  report_ts?: ReportTs;
  options?: Options;
}
/**
 * A catalog alias the gateway loaded, and whether it may serve the tier.
 */
export interface AliasOption {
  alias: Alias1;
  provider: Provider1;
  eligible: Eligible1;
  reason: Reason1;
  report_id?: ReportId1;
  report_ts?: ReportTs1;
}
