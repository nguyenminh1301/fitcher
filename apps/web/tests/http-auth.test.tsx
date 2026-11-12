import { cleanup, render, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { createMockApi } from "@/lib/api/mock";
import { createHttpAuth } from "@/lib/api/http/auth";
import { ChatProvider } from "@/lib/chat/ChatContext";

const IDENTITY = { user_id: "lab.viewer", display_name: "Lab Viewer", roles: ["viewer", "admin"] };

function fetcher(replies: Record<string, () => Response>) {
  return vi.fn(async (url: RequestInfo | URL) => replies[String(url)]?.() ?? new Response("{}", { status: 404 }));
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

  it("signs out through the web server and forgets the user", async () => {
    const fetch = fetcher({
      "/api/session": () => Response.json(IDENTITY),
      "/auth/sign-out": () => Response.json({ url: "http://sso.test/logout" }),
    });
    const auth = createHttpAuth(fetch);
    await auth.current();

    expect(await auth.signOut()).toBe("http://sso.test/logout");
    await auth.current();
    expect(fetch.mock.calls.filter(([url]) => url === "/api/session")).toHaveLength(2);
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
