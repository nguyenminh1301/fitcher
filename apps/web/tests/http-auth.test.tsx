import { cleanup, render, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { createMockApi } from "@/lib/api/mock";
import { createHttpAuth } from "@/lib/api/http/auth";
import { ChatProvider } from "@/lib/chat/ChatContext";

const IDENTITY = { user_id: "lab.viewer", display_name: "Lab Viewer", roles: ["viewer", "admin"], mode: "team" as const, exposed: false };

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
    await expect(auth.switchTo("lab.other")).rejects.toThrow("sign out");
  });

  it("is signed out when the session route answers 401", async () => {
    const auth = createHttpAuth(fetcher({ "/api/session": () => Response.json({ error: "signed_out" }, { status: 401 }) }));

    expect(await auth.current()).toBeNull();
    expect(await auth.identities()).toEqual([]);
  });

  it("signs out through the api and forgets the user", async () => {
    const fetch = fetcher({
      "GET /api/session": () => Response.json(IDENTITY),
      "DELETE /api/session": () => new Response(null, { status: 204 }),
    });
    const auth = createHttpAuth(fetch);
    await auth.current();

    expect(await auth.signOut()).toBe("/sign-in");
    await auth.current();
    expect(fetch.mock.calls.filter(([url, init]) => url === "/api/session" && !init?.method)).toHaveLength(2);
  });

  it("signs in with an e-mail and password", async () => {
    const fetch = fetcher({ "POST /api/session": () => new Response(null, { status: 204 }) });

    await createHttpAuth(fetch).signIn("ana@example.com", "correct horse");

    expect(JSON.parse(fetch.mock.calls[0][1]?.body as string)).toEqual({ email: "ana@example.com", password: "correct horse" });
  });

  it.each([[401, "invalid"], [429, "throttled"]] as const)("tells a refused sign-in (%s) apart", async (status, reason) => {
    const auth = createHttpAuth(fetcher({ "POST /api/session": () => Response.json({}, { status }) }));

    await expect(auth.signIn("ana@example.com", "wrong")).rejects.toMatchObject({ reason });
  });

  it("learns whether sign-in through a provider is offered", async () => {
    const auth = createHttpAuth(fetcher({ "/api/session/oidc": () => Response.json({ enabled: true }) }));

    expect(await auth.oidcEnabled()).toBe(true);
    expect(await createHttpAuth(fetcher({})).oidcEnabled()).toBe(false);
  });

  it("reads the pack from the web server", async () => {
    const pack = { name: "shop", display_name: "Shop", roles: ["viewer"] };

    expect(await createHttpAuth(fetcher({ "/api/pack": () => Response.json(pack) })).pack()).toEqual(pack);
  });

  it("sends a signed-out user to sign-in", async () => {
    const auth = createHttpAuth(fetcher({ "/api/session": () => Response.json({}, { status: 401 }), "/api/pack": () => Response.json({ name: "shop", display_name: "Shop", roles: [] }) }));
    const api = { ...createMockApi(), auth };
    const onSignedOut = vi.fn();

    render(<ChatProvider api={api} navigate={vi.fn()} activeId={null} sources={{ auth: "http" }} onSignedOut={onSignedOut}><p>page</p></ChatProvider>);

    await waitFor(() => expect(onSignedOut).toHaveBeenCalledTimes(1));
  });

  it("lets sample features act for the signed-in user", async () => {
    const mock = createMockApi({ identity: async () => IDENTITY });

    expect(await mock.auth.current()).toEqual(IDENTITY);
  });
});
