// The first-run setup from the api (Phase 13), through the web server's /api/setup routes, which pass the
// session cookie on. Anyone signed in may read the status; the api accepts changes only from an admin.

import type { FitcherApi } from "../client";
import { refused } from "./conversations";

export function createHttpSetup(fetcher: typeof fetch = (...args) => fetch(...args)): FitcherApi["setup"] {
  const call = async (url: string, init?: RequestInit) => {
    const response = await fetcher(url, init);
    if (!response.ok) throw await refused(response);
    return response.json();
  };
  return {
    status: () => call("/api/setup/status", { cache: "no-store" }),
    setMode: (mode, admin) => call("/api/setup/mode", {
      method: "PUT", headers: { "content-type": "application/json" }, body: JSON.stringify(admin ? { mode, admin } : { mode }),
    }),
    skip: (id) => call(`/api/setup/steps/${encodeURIComponent(id)}/skip`, { method: "POST" }),
    complete: () => call("/api/setup/complete", { method: "POST" }),
  };
}

export const httpSetup = createHttpSetup();
