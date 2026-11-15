// Generated from the backend Pydantic contract by npm run contracts:generate; do not edit.

export type SourceId = string;
/**
 * @minItems 1
 */
export type Tables = [string, ...string[]];

export interface InstantEstimateRequest {
  source_id: SourceId;
  tables: Tables;
}
