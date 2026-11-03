// @vitest-environment node
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const jar = new Map<string, string>();
vi.mock("next/headers", () => ({ cookies: async () => ({ get: (name: string) => (jar.has(name) ? { name, value: jar.get(name) } : undefined) }) }));

import { POST } from "@/app/api/ask/route";
import { NextRequest } from "next/server";
import { GET as callback } from "@/app/auth/callback/route";
import { GET as signIn } from "@/app/auth/sign-in/route";
import { LOGIN_COOKIE, SESSION_COOKIE } from "@/lib/server/auth";

type Call = { url: string; init: RequestInit };
let calls: Call[];
let replies: Response[];

beforeEach(() => {
  process.env.API_URL = "http://api:8000";
  process.env.APP_URL = "http://app.test";
  jar.clear();
  calls = [];
  replies = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init: RequestInit = {}) => {
    calls.push({ url, init });
    return replies.shift() ?? new Response("{}", { status: 500 });
  }));
});

afterEach(() => {
  delete process.env.API_URL;
  delete process.env.APP_URL;
  vi.unstubAllGlobals();
});

async function signedIn(): Promise<void> {
  const state = new URL(signIn().headers.get("location") as string).searchParams.get("state") as string;
  replies.push(Response.json({ access_token: "access-1", refresh_token: "r", expires_in: 300, refresh_expires_in: 1800 }));
  const done = await callback(new NextRequest(`http://app.test/auth/callback?state=${state}&code=c`, { headers: { cookie: `${LOGIN_COOKIE}=${state}` } }));
  const line = done.headers.getSetCookie().find((item) => item.startsWith(`${SESSION_COOKIE}=`)) as string;
  jar.set(SESSION_COOKIE, line.split(";")[0].slice(SESSION_COOKIE.length + 1));
}

const ask = (body: unknown, signal?: AbortSignal) =>
  POST(new Request("http://app.test/api/ask", { method: "POST", body: JSON.stringify(body), headers: { "content-type": "application/json" }, signal }));

describe("ask route", () => {
  it("forwards the question with the session's token and streams the api's events back", async () => {
    await signedIn();
    const sse = "event: done\ndata: {\"event\":\"done\",\"trace_id\":\"t\"}\n\n";
    replies.push(new Response(sse, { headers: { "content-type": "text/event-stream" } }));
    const controller = new AbortController();

    const response = await ask({ question: "Top products?", timezone: "UTC" }, controller.signal);

    expect(response.headers.get("content-type")).toBe("text/event-stream");
    expect(await response.text()).toBe(sse);
    const call = calls.at(-1) as Call;
    expect(call.url).toBe("http://api:8000/ask");
    expect(new Headers(call.init.headers).get("authorization")).toBe("Bearer access-1");
    expect(JSON.parse(call.init.body as string)).toEqual({ question: "Top products?", timezone: "UTC" });
    expect(call.init.signal).toBeInstanceOf(AbortSignal);
  });

  it("passes the api's refusal through", async () => {
    await signedIn();
    replies.push(Response.json({ detail: "the token holds no role of this pack" }, { status: 403 }));

    const response = await ask({ question: "q" });

    expect(response.status).toBe(403);
    expect(await response.json()).toEqual({ detail: "the token holds no role of this pack" });
  });

  it("is a 401 without a session and never calls the api", async () => {
    const response = await ask({ question: "q" });

    expect(response.status).toBe(401);
    expect(calls).toEqual([]);
  });
});
