// Contracts the backend has no Pydantic model for yet (DECISIONS §7 and §15): the sample-data mode uses
// them until the phase named on each type adds its model and generated type, then deletes it here.

import type { ChartSpec, Result } from "@/lib/contracts";

import type { ConversationThread } from "./conversations";
import type { AskEvent } from "./events";

/** Who is signed in; Keycloak replaces the demo identities in Phase 7. */
export interface Identity {
  user_id: string;
  display_name: string;
  roles: string[];
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
  kind: "answer" | "clarify" | "failed" | "empty" | "blocked";
  question: string;
  /** The blocked notice of a question the input screen stops (kind "blocked"). */
  screened_message?: string;
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
