// Generated from the backend Pydantic contract by npm run contracts:generate; do not edit.

export type Question = string;
export type ConversationId = string | null;
export type Timezone = string | null;

export interface AskRequest {
  question: Question;
  conversation_id?: ConversationId;
  timezone?: Timezone;
}
