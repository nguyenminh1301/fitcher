// The Documents page from the api (Phase 10), through the web server's /api/documents routes. Uploads go
// as multipart forms with one allowed_roles field per role; the api checks type, size and duplicates.

import type { FitcherApi } from "../client";
import { refused } from "./conversations";

export function createHttpDocuments(fetcher: typeof fetch = (...args) => fetch(...args)): FitcherApi["documents"] {
  const document = (id: string) => `/api/documents/${encodeURIComponent(id)}`;
  async function call(url: string, init?: RequestInit): Promise<Response> {
    const response = await fetcher(url, init);
    if (!response.ok) throw await refused(response);
    return response;
  }
  return {
    list: async () => (await call("/api/documents")).json(),
    upload: async (file, roles) => {
      const form = new FormData();
      form.append("file", file, file.name);
      for (const role of roles) form.append("allowed_roles", role);
      return (await call("/api/documents", { method: "POST", body: form })).json();
    },
    remove: async (id) => {
      await call(document(id), { method: "DELETE" });
    },
    setRoles: async (id, roles) => {
      await call(document(id), {
        method: "PATCH", headers: { "content-type": "application/json" }, body: JSON.stringify({ allowed_roles: roles }),
      });
    },
    draft: async (id) => (await call(`${document(id)}/draft`, { method: "POST" })).json(),
  };
}

export const httpDocuments = createHttpDocuments();
