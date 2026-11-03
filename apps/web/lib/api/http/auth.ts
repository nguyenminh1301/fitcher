// Sign-in through Keycloak (Phase 7): the web server holds the session (app/auth/*) and answers who is
// signed in from the api's /me (app/api/session). There is one identity per browser session, so there is
// nothing to switch to.

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
      throw new Error("A Keycloak session has one identity; sign out to use another account.");
    },
    pack: async () => json(await fetcher("/api/pack", { cache: "no-store" })),
    signOut: async () => {
      current = null;
      return (await json<{ url: string }>(await fetcher("/auth/sign-out", { method: "POST" }))).url;
    },
  };
}

export const httpAuth = createHttpAuth();
