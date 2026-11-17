// The owner password through the web server's /api/owner routes, which pass the api's session cookie on.

import type { FitcherApi } from "../client";
import { refused } from "./conversations";

/** Why signing in was refused: a wrong password, or too many wrong ones in a row. */
export class OwnerSignInError extends Error {
  constructor(readonly reason: "wrong" | "throttled" | "unavailable") {
    super(`sign-in refused: ${reason}`);
    this.name = "OwnerSignInError";
  }
}

const json = (method: string, body: unknown): RequestInit => ({
  method, headers: { "content-type": "application/json" }, body: JSON.stringify(body),
});

export function createHttpOwner(fetcher: typeof fetch = (...args) => fetch(...args)): FitcherApi["owner"] {
  const call = async (url: string, init?: RequestInit) => {
    const response = await fetcher(url, init);
    if (!response.ok) throw await refused(response);
    return response;
  };
  return {
    status: async () => (await call("/api/owner/status", { cache: "no-store" })).json(),
    signIn: async (password) => {
      const response = await fetcher("/api/owner/session", json("POST", { password }));
      if (response.status === 401) throw new OwnerSignInError("wrong");
      if (response.status === 429) throw new OwnerSignInError("throttled");
      if (!response.ok) throw new OwnerSignInError("unavailable");
    },
    signOut: async () => {
      await call("/api/owner/session", { method: "DELETE" });
    },
    setPassword: async (newPassword, currentPassword) => {
      await call("/api/owner/password", json("PUT", currentPassword ? { new_password: newPassword, current_password: currentPassword } : { new_password: newPassword }));
    },
    removePassword: async (currentPassword) => {
      await call("/api/owner/password", json("DELETE", { current_password: currentPassword }));
    },
  };
}

export const httpOwner = createHttpOwner();
