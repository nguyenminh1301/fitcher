// Which implementation each feature uses. A phase that wires a feature to the api switches it to
// "http" here (see the Web wiring section of its plan); a "mock" feature shows the Sample data badge.

import type { Feature } from "./client";

export type Source = "mock" | "http";
export type Sources = Record<Feature, Source>;

export const FEATURES: Feature[] = [
  "auth", "chat", "conversations", "feedback", "datasets", "review", "documents",
  "feedbackReview", "evaluation", "runs", "audit", "costs", "models", "sources", "setup", "owner",
];

// The demo build (NEXT_PUBLIC_FITCHER_DEMO=1, .github/workflows/demo.yml) runs every feature on the
// hand-written sample data with no api behind it, so every page shows the Sample data badge.
export const DEMO = process.env.NEXT_PUBLIC_FITCHER_DEMO === "1";

const LIVE: Sources = {
  auth: "http",
  chat: "http",
  conversations: "http",
  feedback: "http",
  datasets: "http",
  review: "http",
  documents: "http",
  feedbackReview: "http",
  evaluation: "http",
  runs: "http",
  audit: "http",
  costs: "http",
  models: "http",
  sources: "http",
  setup: "http",
  owner: "http",
};

export const sources: Sources = DEMO
  ? (Object.fromEntries(FEATURES.map((feature) => [feature, "mock"])) as Sources)
  : LIVE;

export function isSample(feature: Feature, current: Partial<Sources> = sources): boolean {
  return (current[feature] ?? "mock") === "mock";
}
