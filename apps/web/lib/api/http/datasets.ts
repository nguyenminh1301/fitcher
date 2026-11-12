// The Datasets page from the api (Phase 10), through the web server's /api/datasets route, which adds the
// session's access token; the api answers only a pack_reviewer.

import type { FitcherApi } from "../client";
import { refused } from "./conversations";

export function createHttpDatasets(fetcher: typeof fetch = (...args) => fetch(...args)): FitcherApi["datasets"] {
  return {
    list: async () => {
      const response = await fetcher("/api/datasets");
      if (!response.ok) throw await refused(response);
      return response.json();
    },
  };
}

export const httpDatasets = createHttpDatasets();
