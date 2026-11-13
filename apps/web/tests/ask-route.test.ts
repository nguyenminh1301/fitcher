// @vitest-environment node
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const jar = new Map<string, string>();
vi.mock("next/headers", () => ({ headers: async () => new Headers({ host: "app.test" }), cookies: async () => ({ get: (name: string) => (jar.has(name) ? { name, value: jar.get(name) } : undefined) }) }));

import { POST } from "@/app/api/ask/route";
import { NextRequest } from "next/server";
import { SESSION_COOKIE } from "@/lib/server/api";

type Call = { url: string; init: RequestInit };
let calls: Call[];
let replies: Response[];

beforeEach(() => {
  process.env.API_URL = "http://api:8000";
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
  vi.unstubAllGlobals();
});

async function signedIn(): Promise<void> {
  jar.set(SESSION_COOKIE, "s-1");
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
    expect(new Headers(call.init.headers).get("cookie")).toBe(`${SESSION_COOKIE}=s-1`);
    expect(JSON.parse(call.init.body as string)).toEqual({ question: "Top products?", timezone: "UTC" });
    expect(call.init.signal).toBeInstanceOf(AbortSignal);
  });

  it("passes the api's conversation id through", async () => {
    await signedIn();
    const id = "6f1c2c3e-8f4b-4c55-9a35-2f0d8a1b7c10";
    replies.push(new Response("", { headers: { "content-type": "text/event-stream", "x-conversation-id": id } }));

    const response = await ask({ question: "Top products?" });

    expect(response.headers.get("x-conversation-id")).toBe(id);
  });

  it("passes the api's refusal through", async () => {
    await signedIn();
    replies.push(Response.json({ detail: "the token holds no role of this pack" }, { status: 403 }));

    const response = await ask({ question: "q" });

    expect(response.status).toBe(403);
    expect(await response.json()).toEqual({ detail: "the token holds no role of this pack" });
  });

  it("passes the api's refusal of a request without a session as signed out", async () => {
    replies.push(Response.json({ detail: "invalid or expired access token" }, { status: 401 }));

    const response = await ask({ question: "q" });

    expect(response.status).toBe(401);
    expect(new Headers(calls[0].init.headers).get("cookie")).toBeNull();
  });
});
