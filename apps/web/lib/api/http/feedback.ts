// Answer feedback to the api (Phase 9), through the web server's /api/feedback route, which adds the
// session's access token; the api accepts it only for the user's own answer.

import type { FitcherApi } from "../client";
import { refused } from "./conversations";

export function createHttpFeedback(fetcher: typeof fetch = (...args) => fetch(...args)): FitcherApi["feedback"] {
  return {
    send: async (input) => {
      const response = await fetcher("/api/feedback", {
        method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(input),
      });
      if (!response.ok) throw await refused(response);
    },
  };
}

export const httpFeedback = createHttpFeedback();
