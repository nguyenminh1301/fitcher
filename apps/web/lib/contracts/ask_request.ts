// Generated from the backend Pydantic contract by npm run contracts:generate; do not edit.

export type Question = string;
export type ConversationId = string | null;
export type Pack = string | null;
export type Timezone = string | null;
export type EditOfTurn = number | null;
export type RetryOfTurn = number | null;
export type ClarifyOption = string | null;

export interface AskRequest {
  question: Question;
  conversation_id?: ConversationId;
  pack?: Pack;
  timezone?: Timezone;
  edit_of_turn?: EditOfTurn;
  retry_of_turn?: RetryOfTurn;
  clarify_option?: ClarifyOption;
}
