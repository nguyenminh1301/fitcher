// Generated from the backend Pydantic contract by npm run contracts:generate; do not edit.

export type Title = string | null;
export type Pinned = boolean | null;
export type GroupId = string | null;

/**
 * The fields a request changes; ``group_id: null`` takes the conversation out of its group.
 */
export interface ConversationPatch {
  title?: Title;
  pinned?: Pinned;
  group_id?: GroupId;
}
