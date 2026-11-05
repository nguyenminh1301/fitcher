// The Review page from the api (Phase 10), through the web server's /api/review/items routes. The api writes
// approved changes to the pack's working tree and answers only a pack_reviewer.

import type { FitcherApi } from "../client";
import { refused } from "./conversations";

export function createHttpReview(fetcher: typeof fetch = (...args) => fetch(...args)): FitcherApi["review"] {
  const item = (id: string) => `/api/review/items/${encodeURIComponent(id)}`;
  async function call(url: string, init?: RequestInit): Promise<Response> {
    const response = await fetcher(url, init);
    if (!response.ok) throw await refused(response);
    return response;
  }
  return {
    items: async () => (await call("/api/review/items")).json(),
    update: async (id, patch) => {
      await call(item(id), { method: "PATCH", headers: { "content-type": "application/json" }, body: JSON.stringify(patch) });
    },
    approve: async (id) => {
      await call(`${item(id)}/approve`, { method: "POST" });
    },
    remove: async (id) => {
      await call(item(id), { method: "DELETE" });
    },
    testRun: async (id) => (await call(`${item(id)}/test-run`, { method: "POST" })).json(),
  };
}

export const httpReview = createHttpReview();
