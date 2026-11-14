// Data sources from the api (DECISIONS §4, §15), through the web server's /api/sources routes, which pass the
// session on. The api answers only an admin and no response carries a password. A refused call throws a
// SourceError: a failed connection carries one fixed ``reason`` instead of the database's own message, and a
// deletion blocked by marts lists them.

import type { FitcherApi } from "../client";

type Fetcher = typeof fetch;

export type FailureReason = "unreachable" | "refused" | "authentication" | "tls" | "database_not_found" | "permission" | "unknown" | "interrupted";

export class SourceError extends Error {
  constructor(message: string, readonly status: number, readonly reason?: FailureReason, readonly marts?: string[]) {
    super(message);
  }
}

async function failure(response: Response): Promise<SourceError> {
  let detail: unknown;
  try {
    detail = ((await response.json()) as { detail?: unknown; error?: unknown }).detail ?? undefined;
  } catch {
    // The body was not JSON; the status says enough.
  }
  const base = `The api answered ${response.status}`;
  if (typeof detail === "string") return new SourceError(`${base}: ${detail}`, response.status);
  if (detail && typeof detail === "object") {
    const { reason, marts, message } = detail as { reason?: FailureReason; marts?: string[]; message?: string };
    return new SourceError(message ? `${base}: ${message}` : base, response.status, reason, marts);
  }
  return new SourceError(base, response.status);
}

function send(method: string, body?: unknown): RequestInit {
  return body === undefined
    ? { method }
    : { method, headers: { "content-type": "application/json" }, body: JSON.stringify(body) };
}

export function createHttpSources(fetcher: Fetcher = (...args) => fetch(...args)): FitcherApi["sources"] {
  async function json<T>(url: string, init?: RequestInit): Promise<T> {
    const response = await fetcher(url, init);
    if (!response.ok) throw await failure(response);
    return response.json();
  }
  const source = (id: string) => `/api/sources/${encodeURIComponent(id)}`;
  return {
    list: () => json("/api/sources", { cache: "no-store" }),
    test: (body) => json("/api/sources/test", send("POST", body)),
    create: (body) => json("/api/sources", send("POST", body)),
    update: (id, body) => json(source(id), send("PATCH", body)),
    remove: async (id, confirm) => {
      const response = await fetcher(`${source(id)}?confirm=${encodeURIComponent(confirm)}`, { method: "DELETE" });
      if (!response.ok) throw await failure(response);
    },
    tables: (id, refresh = false) => json(`${source(id)}/tables${refresh ? "?refresh=true" : ""}`, { cache: "no-store" }),
    changeTables: (id, change) => json(`${source(id)}/tables`, send("PUT", change)),
    sync: (id) => json(`${source(id)}/sync`, send("POST")),
    cancel: (id) => json(`${source(id)}/sync/cancel`, send("POST")),
    syncs: (id) => json(`${source(id)}/syncs`, { cache: "no-store" }),
    upload: (file) => {
      const form = new FormData();
      form.append("file", file);
      // The browser sets the multipart boundary itself, so no content type is given.
      return json("/api/sources/files", { method: "POST", body: form });
    },
    loadFile: (id, body) => json(`/api/sources/files/${encodeURIComponent(id)}/load`, send("POST", body)),
  };
}

export const httpSources = createHttpSources();
