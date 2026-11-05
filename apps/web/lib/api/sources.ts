// Which implementation each feature uses. A phase that wires a feature to the api switches it to
// "http" here (see the Web wiring section of its plan); a "mock" feature shows the Sample data badge.

import type { Feature } from "./client";

export type Source = "mock" | "http";
export type Sources = Record<Feature, Source>;

export const FEATURES: Feature[] = [
  "auth", "chat", "conversations", "feedback", "datasets", "review", "documents",
  "feedbackReview", "evaluation", "runs", "audit", "costs", "users", "models",
];

export const sources: Sources = {
  auth: "http",
  chat: "http",
  conversations: "http",
  feedback: "http",
  datasets: "http",
  review: "http",
  documents: "http",
  feedbackReview: "mock",
  evaluation: "mock",
  runs: "mock",
  audit: "mock",
  costs: "mock",
  users: "mock",
  models: "http",
};

export function isSample(feature: Feature, current: Partial<Sources> = sources): boolean {
  return (current[feature] ?? "mock") === "mock";
}
