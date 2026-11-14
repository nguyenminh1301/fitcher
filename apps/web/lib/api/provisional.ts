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

/** Who a request acts as: the signed-in account, or the owner in individual mode; demo identities on sample data. */
export interface Identity {
  user_id: string;
  display_name: string;
  roles: string[];
  /** Individual mode has no sign-in; absent on sample data, which behaves as team mode. */
  mode?: "individual" | "team";
  /** Individual mode reachable through a name other than localhost (DECISIONS §9). */
  exposed?: boolean;
}

/** Why a sign-in was refused: a wrong e-mail or password, or too many failures in a row. */
export class SignInError extends Error {
  constructor(readonly reason: "invalid" | "throttled" | "unavailable") {
    super(`sign-in refused: ${reason}`);
  }
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
