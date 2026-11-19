// Generated from the backend Pydantic contract by npm run contracts:generate; do not edit.

export type ProviderId = string | null;
export type Model = string | null;
export type Chain = ChainLink[] | null;
export type ProviderId1 = string;
export type Model1 = string;

/**
 * One model as the tier's whole chain (``provider_id`` and ``model``), or a whole ``chain``.
 */
export interface TierChange {
  provider_id?: ProviderId;
  model?: Model;
  chain?: Chain;
}
export interface ChainLink {
  provider_id: ProviderId1;
  model: Model1;
}
