// The real api, feature by feature. Each phase that wires a feature replaces its methods here and
// switches the feature to "http" in lib/api/sources.ts; until then every method says it is not wired.

import type { Feature, FitcherApi } from "../client";

export class NotWiredError extends Error {
  constructor(readonly feature: Feature) {
    super(`The ${feature} feature is not connected to the api yet; it runs on sample data.`);
  }
}

function notWired<T extends object>(feature: Feature): T {
  return new Proxy({} as T, {
    get: () => () => {
      throw new NotWiredError(feature);
    },
  });
}

function asyncNotWired<T extends object>(feature: Feature): T {
  return new Proxy({} as T, {
    get: () => () => Promise.reject(new NotWiredError(feature)),
  });
}

export const httpApi: FitcherApi = {
  auth: asyncNotWired("auth"),
  chat: notWired("chat"),
  conversations: asyncNotWired("conversations"),
  feedback: asyncNotWired("feedback"),
  datasets: asyncNotWired("datasets"),
  review: asyncNotWired("review"),
  documents: asyncNotWired("documents"),
  feedbackReview: asyncNotWired("feedbackReview"),
  evaluation: asyncNotWired("evaluation"),
  runs: asyncNotWired("runs"),
  audit: asyncNotWired("audit"),
  costs: asyncNotWired("costs"),
  users: asyncNotWired("users"),
};
