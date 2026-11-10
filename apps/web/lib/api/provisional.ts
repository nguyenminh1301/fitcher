// Contracts the backend has no Pydantic model for yet (DECISIONS §7 and §15): the sample-data mode uses
// them until the phase named on each type adds its model and generated type, then deletes it here.

import type {
  AuditRow,
  ChartSpec,
  CostRow,
  DatasetView,
  DocumentView,
  EvalReport,
  FeedbackRow,
  Result,
  ReviewItem,
  RunRow,
  TraceItem,
  UserRow,
} from "@/lib/contracts";

import type { ConversationThread } from "./conversations";
import type { AskEvent } from "./events";

/** Who is signed in; Keycloak replaces the demo identities in Phase 7. */
export interface Identity {
  user_id: string;
  display_name: string;
  roles: string[];
}

/** A sample document row; the mock fills the rest of DocumentView, which only the api knows. */
export type SampleDocument = Pick<DocumentView, "id" | "name" | "size" | "status" | "roles" | "uploaded_at"> & {
  error?: string;
};
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
  documents: SampleDocument[];
  feedback: FeedbackRow[];
  eval_reports: EvalReport[];
  runs: RunRow[];
  traces: Record<string, TraceItem[]>;
  audit: AuditRow[];
  costs: CostRow[];
  users: UserRow[];
}
