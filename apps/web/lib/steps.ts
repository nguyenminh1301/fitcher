// Graph nodes (DECISIONS §6) -> the design's progress steps; labels are the `ui.step_<id>` strings.

export type StepId = "understand" | "dates" | "retrieve" | "plan" | "access" | "sql" | "repair" | "check" | "run" | "chart" | "summary";

export const NODE_ORDER = [
  "extract", "resolve_time", "retrieve", "build_spec", "gate", "generate_sql", "guard", "explain", "execute", "check",
  "shape_result", "chart_recommender", "summarize",
] as const;

const STEP_OF_NODE: Record<string, StepId> = {
  extract: "understand",
  resolve_time: "dates",
  retrieve: "retrieve",
  build_spec: "plan",
  gate: "access",
  generate_sql: "sql",
  guard: "check",
  explain: "check",
  execute: "run",
  check: "run",
  shape_result: "chart",
  chart_recommender: "chart",
  summarize: "summary",
};

/** The step a node belongs to; a second or later SQL generation is the repair step. */
export function stepFor(node: string, attempt = 1): StepId | undefined {
  if (node === "generate_sql" && attempt > 1) return "repair";
  return STEP_OF_NODE[node];
}
