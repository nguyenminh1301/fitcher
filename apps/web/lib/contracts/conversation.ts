// Generated from the backend Pydantic contract by npm run contracts:generate; do not edit.

export type Id = string;
export type Title = string;
export type Pinned = boolean;
export type GroupId = string | null;
export type UpdatedAt = string;
export type Pack = string | null;

export interface Conversation {
  id: Id;
  title: Title;
  pinned: Pinned;
  group_id: GroupId;
  updated_at: UpdatedAt;
  pack?: Pack;
}
