// Sign-in with an account of the instance (DECISIONS §9): the api keeps the session and the web server's
// /api/session passes its cookie through. In individual mode every request is the owner, so there is no
// sign-in. There is one identity per browser session, so there is nothing to switch to.

import type { FitcherApi } from "../client";
import { type Identity, SignInError } from "../provisional";

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
    pack: async () => json(await fetcher("/api/pack", { cache: "no-store" })),
    signIn: async (email, password) => {
      const response = await fetcher("/api/session", {
        method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ email, password }),
      });
      if (response.status === 401) throw new SignInError("invalid");
      if (response.status === 429) throw new SignInError("throttled");
      if (!response.ok) throw new SignInError("unavailable");
      current = null;
    },
    oidcEnabled: async () => {
      const response = await fetcher("/api/session/oidc", { cache: "no-store" });
      return response.ok && ((await response.json()) as { enabled?: boolean }).enabled === true;
    },
    signOut: async () => {
      current = null;
      const response = await fetcher("/api/session", { method: "DELETE" });
      // A 401 means the api had already ended the session; anything else that failed leaves it signed in.
      if (!response.ok && response.status !== 401) throw new Error(`sign-out answered ${response.status}`);
      return "/sign-in";
    },
  };
}

export const httpAuth = createHttpAuth();
