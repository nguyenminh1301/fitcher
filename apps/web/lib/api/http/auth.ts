// Who the app acts as (DECISIONS §9): fitcher is a personal app, so /api/session answers the owner. There is
// one identity, so there is nothing to switch to.

import type { FitcherApi } from "../client";
import type { Identity } from "../provisional";

async function json<T>(response: Response): Promise<T> {
  if (!response.ok) throw new Error(`${response.url || "request"} answered ${response.status}`);
  return (await response.json()) as T;
}

export function createHttpAuth(fetcher: typeof fetch = (...args) => fetch(...args)): FitcherApi["auth"] {
  // The signed-in user is read once per page load and shared by every caller.
  let current: Promise<Identity | null> | null = null;
  const load = () =>
    (current ??= fetcher("/api/session", { cache: "no-store" }).then((response) => (response.status === 401 ? null : json<Identity>(response))).catch((error) => {
      current = null;
      throw error;
    }));
  return {
    current: load,
    identities: async () => {
      const identity = await load();
      return identity ? [identity] : [];
    },
    switchTo: async () => {
      throw new Error("A session has one identity; sign out to use another account.");
    },
    // 503 means no pack is active yet: a new instance before its first pack is built.
    pack: async () => {
      const response = await fetcher("/api/pack", { cache: "no-store" });
      return response.status === 503 ? null : json(response);
    },
  };
}

export const httpAuth = createHttpAuth();
