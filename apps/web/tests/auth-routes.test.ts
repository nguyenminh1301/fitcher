// @vitest-environment node
import { NextRequest } from "next/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const jar = new Map<string, string>();
vi.mock("next/headers", () => ({
  headers: async () => new Headers({ host: "app.test", origin: "http://app.test" }),
  cookies: async () => ({ get: (name: string) => (jar.has(name) ? { name, value: jar.get(name) } : undefined) }),
}));

import { DELETE as signOut, GET as session, POST as signIn } from "@/app/api/session/route";
import { GET as oidcAvailability } from "@/app/api/session/oidc/route";
import { GET as oidcStart } from "@/app/auth/oidc/start/route";
import { GET as oidcCallback } from "@/app/auth/oidc/callback/route";
import { SESSION_COOKIE } from "@/lib/server/api";

type Call = { url: string; init: RequestInit; headers: Headers };
let calls: Call[];
let replies: Response[];

beforeEach(() => {
  process.env.API_URL = "http://api:8000";
  jar.clear();
  calls = [];
  replies = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init: RequestInit = {}) => {
    calls.push({ url, init, headers: new Headers(init.headers) });
    return replies.shift() ?? new Response("{}", { status: 500 });
  }));
});

afterEach(() => {
  delete process.env.API_URL;
  vi.unstubAllGlobals();
});

const ME = { user_id: "ana", display_name: "Ana", roles: ["viewer"], active_role: "viewer", mode: "team", exposed: false };
const COOKIE = `${SESSION_COOKIE}=s-1; Path=/; HttpOnly; SameSite=strict; Max-Age=2592000`;

describe("session routes", () => {
  it("answers who the api says the request acts as, forwarding only the session cookie", async () => {
    jar.set(SESSION_COOKIE, "s-1");
    replies.push(Response.json(ME));

    const response = await session();

    expect(await response.json()).toEqual({ user_id: "ana", display_name: "Ana", roles: ["viewer"], mode: "team", exposed: false });
    expect(calls[0].url).toBe("http://api:8000/me");
    expect(calls[0].headers.get("cookie")).toBe(`${SESSION_COOKIE}=s-1`);
    expect(calls[0].headers.get("authorization")).toBeNull();
    expect(calls[0].headers.get("x-forwarded-host")).toBe("app.test");
  });

  it("asks the api even without a cookie, because individual mode has no sign-in", async () => {
    replies.push(Response.json({ ...ME, user_id: "owner", mode: "individual" }));

    const response = await session();

    expect((await response.json()).user_id).toBe("owner");
    expect(calls[0].headers.get("cookie")).toBeNull();
  });

  it("is a 401 when the api signs the request out", async () => {
    replies.push(Response.json({ detail: "invalid or expired access token" }, { status: 401 }));

    const response = await session();

    expect(response.status).toBe(401);
    expect(await response.json()).toEqual({ error: "signed_out" });
  });

  it("signs in through the api and passes its session cookie to the browser", async () => {
    replies.push(new Response(null, { status: 204, headers: { "set-cookie": COOKIE } }));

    const response = await signIn(new Request("http://app.test/api/session", {
      method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ email: "ana@example.com", password: "pw" }),
    }));

    expect(response.status).toBe(204);
    expect(response.headers.getSetCookie()).toEqual([COOKIE]);
    expect(calls[0].url).toBe("http://api:8000/session");
    expect(calls[0].init.method).toBe("POST");
    expect(JSON.parse(calls[0].init.body as string)).toEqual({ email: "ana@example.com", password: "pw" });
  });

  it("passes a refused sign-in through with its status and Retry-After", async () => {
    replies.push(Response.json({ detail: "too many failed sign-ins; try again later" }, { status: 429, headers: { "retry-after": "60" } }));

    const response = await signIn(new Request("http://app.test/api/session", { method: "POST", body: "{}" }));

    expect(response.status).toBe(429);
    expect(response.headers.get("retry-after")).toBe("60");
    expect(response.headers.getSetCookie()).toEqual([]);
  });

  it("signs out through the api, which clears the cookie", async () => {
    jar.set(SESSION_COOKIE, "s-1");
    const cleared = `${SESSION_COOKIE}=""; Max-Age=0; Path=/; HttpOnly; SameSite=strict`;
    replies.push(new Response(null, { status: 204, headers: { "set-cookie": cleared } }));

    const response = await signOut();

    expect(response.status).toBe(204);
    expect(response.headers.getSetCookie()).toEqual([cleared]);
    expect(calls[0].init.method).toBe("DELETE");
    expect(calls[0].headers.get("cookie")).toBe(`${SESSION_COOKIE}=s-1`);
  });
});

describe("OIDC routes", () => {
  it("tells the sign-in page whether a provider is set up", async () => {
    replies.push(Response.json({ enabled: true }));

    expect(await (await oidcAvailability()).json()).toEqual({ enabled: true });
    expect(calls[0].url).toBe("http://api:8000/session/oidc");
  });

  it("sends the browser on to the provider the api names", async () => {
    replies.push(new Response(null, { status: 302, headers: { location: "https://idp.example.com/auth?state=s" } }));

    const response = await oidcStart();

    expect(response.status).toBe(302);
    expect(response.headers.get("location")).toBe("https://idp.example.com/auth?state=s");
    expect(calls[0].url).toBe("http://api:8000/session/oidc/start");
    expect(calls[0].init.redirect).toBe("manual");
  });

  it("forwards the provider's callback and passes the api's page and cookie back", async () => {
    replies.push(new Response("<meta http-equiv=\"refresh\" content=\"0;url=/\">", {
      status: 200, headers: { "content-type": "text/html", "set-cookie": COOKIE },
    }));

    const response = await oidcCallback(new NextRequest("http://app.test/auth/oidc/callback?state=s&code=c"));

    expect(response.status).toBe(200);
    expect(await response.text()).toContain("refresh");
    expect(response.headers.get("content-type")).toBe("text/html");
    expect(response.headers.getSetCookie()).toEqual([COOKIE]);
    expect(calls[0].url).toBe("http://api:8000/session/oidc/callback?state=s&code=c");
  });

  it("passes a failed callback's redirect to the sign-in page", async () => {
    replies.push(new Response(null, { status: 303, headers: { location: "/sign-in?error=oidc" } }));

    const response = await oidcCallback(new NextRequest("http://app.test/auth/oidc/callback?error=access_denied"));

    expect(response.status).toBe(303);
    expect(response.headers.get("location")).toBe("/sign-in?error=oidc");
  });
});
