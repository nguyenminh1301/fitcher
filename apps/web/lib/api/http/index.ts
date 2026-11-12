// The real api, feature by feature; lib/api/sources.ts chooses between it and the sample data.

import type { FitcherApi } from "../client";
import { httpAudit, httpCosts, httpEvaluation, httpFeedbackReview, httpRuns, httpUsers } from "./admin";
import { httpAuth } from "./auth";
import { httpChat } from "./chat";
import { httpConversations } from "./conversations";
import { httpDatasets } from "./datasets";
import { httpDocuments } from "./documents";
import { httpFeedback } from "./feedback";
import { httpModels } from "./models";
import { httpReview } from "./review";
import { httpSetup } from "./setup";

export const httpApi: FitcherApi = {
  auth: httpAuth,
  chat: httpChat,
  conversations: httpConversations,
  feedback: httpFeedback,
  datasets: httpDatasets,
  review: httpReview,
  documents: httpDocuments,
  feedbackReview: httpFeedbackReview,
  evaluation: httpEvaluation,
  runs: httpRuns,
  audit: httpAudit,
  costs: httpCosts,
  users: httpUsers,
  models: httpModels,
  setup: httpSetup,
};
