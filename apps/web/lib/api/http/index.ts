// The real api, feature by feature. Each phase that wires a feature replaces its methods here and
// switches the feature to "http" in lib/api/sources.ts; until then every method says it is not wired.

import type { Feature, FitcherApi } from "../client";
import { httpAuth } from "./auth";
import { httpChat } from "./chat";
import { httpConversations } from "./conversations";
import { httpDatasets } from "./datasets";
import { httpDocuments } from "./documents";
import { httpFeedback } from "./feedback";
import { httpModels } from "./models";
import { httpReview } from "./review";

export class NotWiredError extends Error {
  constructor(readonly feature: Feature) {
    super(`The ${feature} feature is not connected to the api yet; it runs on sample data.`);
  }
}

function asyncNotWired<T extends object>(feature: Feature): T {
  return new Proxy({} as T, {
    get: () => () => Promise.reject(new NotWiredError(feature)),
  });
}

export const httpApi: FitcherApi = {
  auth: httpAuth,
  chat: httpChat,
  conversations: httpConversations,
  feedback: httpFeedback,
  datasets: httpDatasets,
  review: httpReview,
  documents: httpDocuments,
  feedbackReview: asyncNotWired("feedbackReview"),
  evaluation: asyncNotWired("evaluation"),
  runs: asyncNotWired("runs"),
  audit: asyncNotWired("audit"),
  costs: asyncNotWired("costs"),
  users: asyncNotWired("users"),
  models: httpModels,
};
