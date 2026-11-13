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
export type { ProviderView } from "./provider_view";
export type { ProviderCreate } from "./provider_create";
export type { ProviderUpdate } from "./provider_update";
export type { ProviderModels } from "./provider_models";
export type { ProviderTestRequest } from "./provider_test_request";
export type { ProviderTestResult } from "./provider_test_result";
export type { EmbeddingView, EvalStatus, ModelTiersView, TierView } from "./model_tiers_view";
export type { TierChange } from "./tier_change";
export type { EmbeddingChange } from "./embedding_change";
export type { ClassifierStatus } from "./classifier_status";
export type { DatasetView } from "./dataset_view";
export type { EvidenceRef, ReviewedSpec, ReviewEvidence, ReviewItem, SpecFilter } from "./review_item";
export type { ReviewItemPatch } from "./review_item_patch";
export type { DocumentView } from "./document_view";
export type { DocumentList } from "./document_list";
export type { DocumentRolesChange } from "./document_roles_change";
export type { DraftResult } from "./draft_result";
export type { RunRow } from "./run_row";
export type { RunTrace, TraceItem } from "./run_trace";
export type { AuditRow } from "./audit_row";
export type { CostRow } from "./cost_row";
export type { FeedbackRow } from "./feedback_row";
export type { ProposalResult } from "./proposal_result";
export type { EvalLayer, EvalReportView as EvalReport, FailedCase } from "./eval_report_view";
export type { EvalRunStarted } from "./eval_run_started";
export type { UserView as UserRow } from "./user_view";
export type { UserChange } from "./user_change";
export type { NewUser } from "./new_user";
export type { PasswordReset } from "./password_reset";
export type { SetupStatus, SetupStep } from "./setup_status";
export type { SetupModeChange } from "./setup_mode_change";
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
