// Generated from the backend Pydantic contract by npm run contracts:generate; do not edit.

export type Added = string[];
export type Updated = string[];
export type SkippedApproved = string[];

/**
 * Review ids (``<file stem>.<item id>``) of the items a draft added, refreshed or left because they are approved.
 */
export interface DraftResult {
  added: Added;
  updated: Updated;
  skipped_approved: SkippedApproved;
}
