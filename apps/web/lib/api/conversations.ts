// A conversation as the chat app holds it. Conversation and ConversationGroup are the api's contracts;
// a turn adds what only the browser knows: the question's language for its bubble, events the browser
// raises itself (a stopped or failed stream) and the user's rating until feedback has its api (Phase 9).

import type { Conversation, ConversationGroup } from "@/lib/contracts";

import type { AskEvent } from "./events";

export type { Conversation, ConversationGroup };

export interface Turn {
  turn: number;
  revision: number;
  question: string;
  question_lang: string;
  events: AskEvent[];
  feedback?: "like" | "dislike";
}

export interface ConversationThread {
  conversation: Conversation;
  turns: Turn[];
}
