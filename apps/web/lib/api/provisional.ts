// Contracts the backend has no Pydantic model for yet (DECISIONS §7 and §15): the sample-data mode uses
// them until the phase named on each type adds its model and generated type, then deletes it here.

import type { Result } from "@/lib/contracts";

/** DECISIONS §7 ChartSpec; model and generated type arrive in Phase 7. */
export type ChartType = "bar" | "line" | "pie" | "scatter" | "kpi" | "table" | "grouped_bar";
export interface ChartSpec {
  type: ChartType;
  x: string;
  y: string[];
  series?: string | null;
  sort?: "asc" | "desc" | null;
  format?: string | null;
  orientation?: "vertical" | "horizontal";
  allowed_types: ChartType[];
}

/** Stream events of /ask in DECISIONS §6 order; models arrive in Phase 7. */
type Traced = { trace_id: string };
export type AskEvent =
  | (Traced & { event: "status"; node: string; phase: "start" | "end"; attempt?: number })
  | (Traced & { event: "clarify"; question: string; options: { id: string; label: string }[]; lang: string })
  | (Traced & { event: "deny"; message: string; role: string; blocked: string[]; lang: string })
  | (Traced & { event: "sql"; sql: string; attempt: number })
  | (Traced & { event: "result"; result: Result })
  | (Traced & { event: "chart_spec"; spec: ChartSpec })
  | (Traced & { event: "summary"; text: string; lang: string; warnings: string[] })
  | (Traced & { event: "done" })
  | (Traced & { event: "error"; kind: "failed" | "network" | "internal" | "stopped"; message: string; sql?: string; error?: string });

/** The body of POST /ask; Phase 7 (edit and retry: Phase 8). */
export interface AskRequest {
  question: string;
  conversation_id?: string;
  time_zone: string;
  edit_of_turn?: number;
  retry_of_turn?: number;
}

/** Who is signed in; Keycloak replaces the demo identities in Phase 7. */
export interface Identity {
  user_id: string;
  display_name: string;
  roles: string[];
}

/** Conversations and their turns; Phase 8. */
export interface Conversation {
  id: string;
  title: string;
  pinned: boolean;
  group_id: string | null;
  updated_at: string;
}
export interface ConversationGroup {
  id: string;
  name: string;
}
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

/** POST /feedback; Phase 9. */
export interface FeedbackInput {
  trace_id: string;
  rating: "like" | "dislike";
  note?: string;
}

/** Console rows; Datasets, Review and Documents in Phase 10, the rest in Phase 12. */
export interface DatasetView {
  id: string;
  description: string;
  grain: string;
  time_column: string;
  readable_roles: string[];
  columns: { name: string; type: string; role: string; description: string }[];
}
export interface ReviewItem {
  id: string;
  file: string;
  name: string;
  kind: "item" | "proposal";
  status: "draft" | "approved";
  confidence: number;
  body: string;
  formula?: string;
  evidence?: { source: string; quote?: string; deleted?: boolean };
  test_result?: Result;
}
export interface DocumentRow {
  id: string;
  name: string;
  size: number;
  status: "processing" | "indexed" | "failed";
  error?: string;
  roles: string[];
  uploaded_at: string;
}
export interface FeedbackRow {
  trace_id: string;
  ts: string;
  user_id: string;
  rating: "like" | "dislike";
  question: string;
  note?: string;
  run_status: string;
  proposal?: "proposed" | "dismissed";
}
export interface EvalReport {
  id: string;
  ts: string;
  passed: boolean;
  threshold: number;
  layers: Record<string, { passed: number; failed: number; not_scored: number }>;
  categories: Record<string, string>;
  failed_cases: { case_id: string; category: string; reason: string }[];
}
export interface RunRow {
  trace_id: string;
  ts: string;
  user_id: string;
  role: string;
  question: string;
  status: string;
  latency_ms: number;
  cost_usd: number;
}
export interface TraceItem {
  name: string;
  kind?: "llm" | "sql" | "access" | "search";
  status?: "ok" | "err" | "deny";
  ms?: number;
  meta?: string[];
  sql?: string;
  error?: string;
}
export interface AuditRow {
  ts: string;
  trace_id: string;
  user_id: string;
  role: string;
  decision: "ALLOW" | "DENY";
  dataset: string;
  blocked_tables: string[];
  reason: string;
}
export interface CostRow {
  day: string;
  alias: string;
  model: string;
  calls: number;
  cost_usd: number;
}
export interface UserRow {
  id: string;
  username: string;
  display_name: string;
  roles: string[];
  enabled: boolean;
}

/** A sample answer the mock chat streams (packs/<pack>/sample_data/scenarios.json). */
export interface Scenario {
  id: string;
  lang: string;
  match: { any: string[]; all?: string[] };
  allowed_roles: string[];
  kind: "answer" | "clarify" | "failed" | "empty";
  question: string;
  sql?: string;
  repair?: { sql: string; error: string };
  result?: Result;
  chart_spec?: ChartSpec;
  summary?: string;
  warnings?: string[];
  clarify?: { question: string; options: { id: string; label: string }[] };
  error?: string;
  deny_message: string;
  blocked: string[];
}
export interface ScenarioFile {
  suggestions: { text: string; lang: string }[];
  scenarios: Scenario[];
}

/** The pack's sample console (packs/<pack>/sample_data/console.json). */
export interface ConsoleFile {
  pack: { name: string; display_name: string };
  pack_roles: string[];
  identities: Identity[];
  conversations: ConversationThread[];
  datasets: DatasetView[];
  review_items: ReviewItem[];
  documents: DocumentRow[];
  feedback: FeedbackRow[];
  eval_reports: EvalReport[];
  runs: RunRow[];
  traces: Record<string, TraceItem[]>;
  audit: AuditRow[];
  costs: CostRow[];
  users: UserRow[];
}
