// Who the app acts as (DECISIONS §9): fitcher is a personal app, so /api/session answers the owner. There is
// one identity, so there is nothing to switch to.

import type { FitcherApi } from "../client";
import type { Identity } from "../provisional";

/**
 * The api refused this browser before signing in could help (403 from its address checks): a name missing from
 * FITCHER_ALLOWED_HOSTS, a reverse proxy relaying a loopback host, or another machine before a password is set.
 * `reason` is the api's own explanation, which says what to change.
 */
export class AccessRefused extends Error {
  constructor(readonly reason: string) {
    super(reason);
  }
}

async function json<T>(response: Response): Promise<T> {
  if (response.status === 403) {
    const body = (await response.json().catch(() => ({}))) as { detail?: unknown };
    throw new AccessRefused(typeof body.detail === "string" ? body.detail : "");
  }
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
    // 503 means no pack is active yet; 401 means the owner password asks for a session first, which the
    // session check sends to the sign-in page.
    pack: async () => {
      const response = await fetcher("/api/pack", { cache: "no-store" });
      return response.status === 503 || response.status === 401 ? null : json(response);
    },
    choosePack: async (name) => json(await fetcher("/api/pack", {
      method: "PUT", headers: { "content-type": "application/json" }, body: JSON.stringify({ name }),
    })),
  };
}

export const httpAuth = createHttpAuth();
