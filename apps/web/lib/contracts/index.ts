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
export type { AliasOption, ModelTier, ModelTiers } from "./model_tiers";
export type { ModelTierChange } from "./model_tier_change";
export type { DatasetView } from "./dataset_view";
export type { EvidenceRef, ReviewEvidence, ReviewItem } from "./review_item";
export type { ReviewItemPatch } from "./review_item_patch";
export type { DocumentView } from "./document_view";
export type { DocumentList } from "./document_list";
export type { DocumentRolesChange } from "./document_roles_change";
export type { DraftResult } from "./draft_result";
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
