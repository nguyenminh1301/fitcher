// The sample chat: a question is matched to one of the pack's scenarios and streamed with the event
// sequences of DECISIONS §6, step by step, so the answer view behaves as it will against /ask.

import { DICTIONARIES, translate } from "@/lib/i18n";
import { fold, langOf } from "@/lib/text";

import type { FitcherApi } from "../client";
import type { AskEvent } from "../events";
import type { Identity, Scenario } from "../provisional";
import type { SampleData } from "./load";

const BEFORE_SQL = ["extract", "resolve_time", "retrieve", "build_spec", "gate"];
const SQL_ATTEMPT = ["generate_sql", "guard", "explain", "execute", "check"];
const AFTER_SQL = ["shape_result", "chart_recommender", "summarize"];

/** An event before the run's trace id is attached (Omit applied to each member of the union). */
type Untraced = AskEvent extends infer E ? (E extends unknown ? Omit<E, "trace_id"> : never) : never;

/** The scenario whose keywords the question contains most, or null. */
export function matchScenario(question: string, scenarios: Scenario[]): Scenario | null {
  const text = ` ${fold(question)} `;
  let best: Scenario | null = null;
  let bestScore = 0;
  for (const scenario of scenarios) {
    if (!(scenario.match.all ?? []).every((word) => text.includes(` ${fold(word)} `) || text.includes(fold(word)))) continue;
    const score = scenario.match.any.filter((word) => text.includes(fold(word))).length;
    if (score > bestScore) {
      best = scenario;
      bestScore = score;
    }
  }
  return best;
}

function traceId(): string {
  return Array.from({ length: 32 }, () => Math.floor(Math.random() * 16).toString(16)).join("");
}

function plan(scenario: Scenario | null, question: string, identity: Identity | null): Untraced[] {
  const status = (node: string, attempt?: number) => ({ event: "status" as const, node, phase: "end" as const, attempt: attempt ?? null });
  if (scenario === null) {
    const lang = langOf(question);
    return [status("extract"), { event: "summary", text: translate(DICTIONARIES.en, DICTIONARIES[lang], "sample.unmatched"), lang, warnings: [] }, { event: "done" }];
  }
  const head = BEFORE_SQL.map((node) => status(node));
  const role = identity?.roles.find((item) => scenario.allowed_roles.includes(item));
  if (!role) {
    const asked = identity?.roles[0] ?? "";
    return [...head, { event: "deny", message: scenario.deny_message, role: asked, blocked: scenario.blocked, lang: scenario.lang }, { event: "done" }];
  }
  if (scenario.kind === "clarify" && scenario.clarify) {
    return [...head.slice(0, 4), { event: "clarify", ...scenario.clarify, lang: scenario.lang }, { event: "done" }];
  }
  const attempts: Untraced[] = [];
  const sqls = scenario.kind === "failed" ? [scenario.sql ?? "", scenario.sql ?? "", scenario.sql ?? "", scenario.sql ?? ""] : [...(scenario.repair ? [scenario.repair.sql] : []), scenario.sql ?? ""];
  sqls.forEach((sql, index) => {
    attempts.push(status("generate_sql", index + 1), { event: "sql", sql, attempt: index + 1 }, ...SQL_ATTEMPT.slice(1).map((node) => status(node)));
  });
  if (scenario.kind === "failed") {
    return [...head, ...attempts, { event: "error", kind: "failed", message: scenario.error ?? "", sql: scenario.sql ?? null, error: scenario.error ?? null }];
  }
  const result = scenario.result ?? { columns: [{ name: "value", type: "number", role: "measure" }], rows: [], row_count: 0 };
  return [
    ...head,
    ...attempts,
    ...AFTER_SQL.slice(0, 1).map((node) => status(node)),
    { event: "result", result },
    ...(scenario.chart_spec ? [status("chart_recommender"), { event: "chart_spec" as const, spec: scenario.chart_spec }] : []),
    status("summarize"),
    { event: "summary", text: scenario.summary ?? "", lang: scenario.lang, warnings: scenario.warnings ?? [] },
    { event: "done" },
  ];
}

function pause(ms: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve) => {
    if (ms <= 0 || signal.aborted) return resolve();
    const timer = setTimeout(resolve, ms);
    signal.addEventListener("abort", () => {
      clearTimeout(timer);
      resolve();
    }, { once: true });
  });
}

export function createMockChat(
  load: () => Promise<SampleData>,
  identity: () => Promise<Identity | null>,
  options: { stepMs?: number } = {},
): FitcherApi["chat"] {
  const stepMs = options.stepMs ?? 280;
  return {
    suggestions: async () => (await load()).scenarios.suggestions,
    async *ask(request, signal) {
      const data = await load();
      const events = plan(matchScenario(request.question, data.scenarios.scenarios), request.question, await identity());
      const trace_id = traceId();
      for (const event of events) {
        await pause(event.event === "status" ? stepMs : stepMs / 2, signal);
        if (signal.aborted) {
          yield { event: "error", kind: "stopped", message: "stopped", sql: null, error: null, trace_id };
          return;
        }
        yield { ...event, trace_id } as AskEvent;
        if (signal.aborted && event.event !== "done") {
          yield { event: "error", kind: "stopped", message: "stopped", sql: null, error: null, trace_id };
          return;
        }
      }
    },
  };
}
