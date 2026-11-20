import { cleanup, render, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { createMockApi } from "@/lib/api/mock";
import { AccessRefused, createHttpAuth } from "@/lib/api/http/auth";
import { ChatProvider } from "@/lib/chat/ChatContext";

const IDENTITY = { user_id: "dev.viewer", display_name: "Lab Viewer", roles: ["viewer", "admin"], mode: "team" as const, exposed: false };

function fetcher(replies: Record<string, (init?: RequestInit) => Response>) {
  return vi.fn(async (url: RequestInfo | URL, init?: RequestInit) => {
    const key = `${init?.method ?? "GET"} ${String(url)}`;
    return (replies[key] ?? replies[String(url)])?.(init) ?? new Response("{}", { status: 404 });
  });
}

afterEach(cleanup);

describe("http auth", () => {
  it("reads the signed-in user once per page and offers no other identity", async () => {
    const fetch = fetcher({ "/api/session": () => Response.json(IDENTITY) });
    const auth = createHttpAuth(fetch);

    expect(await auth.current()).toEqual(IDENTITY);
    expect(await auth.identities()).toEqual([IDENTITY]);
    expect(fetch).toHaveBeenCalledTimes(1);
    await expect(auth.switchTo("dev.other")).rejects.toThrow("sign out");
  });

  it("reads the pack from the web server", async () => {
    const pack = { name: "shop", display_name: "Shop", roles: ["viewer"] };

    expect(await createHttpAuth(fetcher({ "/api/pack": () => Response.json(pack) })).pack()).toEqual(pack);
  });

  it("reads no pack while signed out, so the page can go on to sign in", async () => {
    const answer = () => Response.json({ error: "signed_out" }, { status: 401 });

    expect(await createHttpAuth(fetcher({ "/api/pack": answer })).pack()).toBeNull();
  });

  it("reads no pack while none is active, so a new instance still loads", async () => {
    const answer = () => Response.json({ detail: "no pack is active" }, { status: 503 });

    expect(await createHttpAuth(fetcher({ "/api/pack": answer })).pack()).toBeNull();
  });

  it("lets sample features act for the signed-in user", async () => {
    const mock = createMockApi({ identity: async () => IDENTITY });

    expect(await mock.auth.current()).toEqual(IDENTITY);
  });

  it("passes the api's reason on when the api refuses this browser outright", async () => {
    const reason = "the request names '127.0.0.1:3000' but came through a reverse proxy (connection: close)";
    const auth = createHttpAuth(fetcher({ "/api/session": () => Response.json({ detail: reason }, { status: 403 }) }));

    const refused = await auth.current().catch((error: unknown) => error);
    expect(refused).toBeInstanceOf(AccessRefused);
    expect((refused as AccessRefused).reason).toBe(reason);
  });

  it("asks again after a signed-out answer, so signing in without a page load opens the app", async () => {
    let signedIn = false;
    const fetch = fetcher({ "/api/session": () => (signedIn ? Response.json(IDENTITY) : Response.json({ error: "signed_out" }, { status: 401 })) });
    const auth = createHttpAuth(fetch);

    expect(await auth.current()).toBeNull();
    signedIn = true;
    expect(await auth.current()).toEqual(IDENTITY);
    expect(await auth.current()).toEqual(IDENTITY);
    expect(fetch).toHaveBeenCalledTimes(2);
  });
});
