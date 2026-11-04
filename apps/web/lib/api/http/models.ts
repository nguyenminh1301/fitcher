// The Models page from the api (Phase 9D), through the web server's /api/admin/models routes, which add
// the session's access token; the api answers only an admin and accepts only an eligible alias.

import type { FitcherApi } from "../client";
import { refused } from "./conversations";

export function createHttpModels(fetcher: typeof fetch = (...args) => fetch(...args)): FitcherApi["models"] {
  return {
    list: async () => {
      const response = await fetcher("/api/admin/models");
      if (!response.ok) throw await refused(response);
      return response.json();
    },
    set: async (tier, alias) => {
      const response = await fetcher(`/api/admin/models/${encodeURIComponent(tier)}`, {
        method: "PUT", headers: { "content-type": "application/json" }, body: JSON.stringify({ alias }),
      });
      if (!response.ok) throw await refused(response);
      return response.json();
    },
  };
}

export const httpModels = createHttpModels();
