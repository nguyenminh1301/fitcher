// The backend contracts, generated from Pydantic (DECISIONS §7). Types that have no backend model yet
// live in lib/api/provisional.ts until their phase adds one.
export type { ColumnInfo, Result } from "./result";
export type { Filter, Period, QuerySpec } from "./query_spec";
export type { ChartSpec } from "./chart_spec";
export type { AskRequest } from "./ask_request";
export type { Conversation } from "./conversation";
export type { ConversationGroup } from "./conversation_group";
export type { ConversationPatch } from "./conversation_patch";
export type { ConversationThread as ConversationThreadContract, ConversationTurn } from "./conversation_thread";
export type { GroupInput } from "./group_input";
export type { FeedbackInput } from "./feedback_input";
export type {
  AskEvent as StreamEvent,
  ChartSpecEvent,
  ClarifyEvent,
  DenyEvent,
  DoneEvent,
  ErrorEvent,
  ResultEvent,
  SqlEvent,
  StatusEvent,
  SummaryEvent,
} from "./ask_event";

import type { ChartSpec } from "./chart_spec";
import type { Result } from "./result";

/** One cell of a result row. */
export type Cell = Result["rows"][number][number];

/** A chart type of DECISIONS §8. */
export type ChartType = ChartSpec["type"];
