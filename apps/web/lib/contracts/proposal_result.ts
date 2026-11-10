// Generated from the backend Pydantic contract by npm run contracts:generate; do not edit.

export type Proposed = boolean;
export type ProposalId = string | null;
export type Question = string | null;
export type Reason = string | null;

/**
 * The proposal stored from one run, or why the run cannot become one.
 */
export interface ProposalResult {
  proposed: Proposed;
  proposal_id?: ProposalId;
  question?: Question;
  reason?: Reason;
}
