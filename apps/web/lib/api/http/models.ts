// Model providers, tiers, the embedding and the screening classifier from the api (Phase 14), through the web
// server's /api/providers, /api/models and /api/screening routes, which add the session's access token. The
// api answers only an admin; no response carries a provider key, only whether one is set and its last four
// characters.

import type { FitcherApi } from "../client";
import { refused } from "./conversations";

type Fetcher = typeof fetch;

async function json<T>(fetcher: Fetcher, url: string, init?: RequestInit): Promise<T> {
  const response = await fetcher(url, init);
  if (!response.ok) throw await refused(response);
  return response.json();
}

function send(method: string, body?: unknown): RequestInit {
  return body === undefined
    ? { method }
    : { method, headers: { "content-type": "application/json" }, body: JSON.stringify(body) };
}

export function createHttpModels(fetcher: Fetcher = (...args) => fetch(...args)): FitcherApi["models"] {
  const provider = (id: string) => `/api/providers/${encodeURIComponent(id)}`;
  return {
    providers: () => json(fetcher, "/api/providers"),
    addProvider: (body) => json(fetcher, "/api/providers", send("POST", body)),
    changeProvider: (id, body) => json(fetcher, provider(id), send("PATCH", body)),
    removeProvider: async (id) => {
      const response = await fetcher(provider(id), { method: "DELETE" });
      if (!response.ok) throw await refused(response);
    },
    providerModels: (id) => json(fetcher, `${provider(id)}/models`),
    testProvider: (id, model) => json(fetcher, `${provider(id)}/test`, send("POST", model ? { model } : {})),
    tiers: () => json(fetcher, "/api/models/tiers"),
    setTier: (tier, change) => json(fetcher, `/api/models/tiers/${encodeURIComponent(tier)}`, send("PUT", change)),
    setEmbedding: (change) => json(fetcher, "/api/models/embedding", send("PUT", change)),
    classifier: () => json(fetcher, "/api/screening/classifier"),
    setClassifier: (enabled) => json(fetcher, "/api/screening/classifier", send(enabled ? "POST" : "DELETE")),
  };
}

export const httpModels = createHttpModels();
