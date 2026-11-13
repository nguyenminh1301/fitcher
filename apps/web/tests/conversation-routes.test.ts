// @vitest-environment node
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const jar = new Map<string, string>();
vi.mock("next/headers", () => ({ headers: async () => new Headers({ host: "app.test" }), cookies: async () => ({ get: (name: string) => (jar.has(name) ? { name, value: jar.get(name) } : undefined) }) }));

import { NextRequest } from "next/server";
import { GET as groups, POST as createGroup } from "@/app/api/conversation-groups/route";
import { DELETE as removeGroup, PATCH as renameGroup } from "@/app/api/conversation-groups/[id]/route";
import { GET as list } from "@/app/api/conversations/route";
import { DELETE as remove, GET as read, PATCH as update } from "@/app/api/conversations/[id]/route";
import { GET as search } from "@/app/api/conversations/search/route";
import { POST as feedback } from "@/app/api/feedback/route";
import { POST as upload } from "@/app/api/documents/route";
import { POST as draft } from "@/app/api/documents/[id]/draft/route";
import { GET as reviewItems } from "@/app/api/review/items/route";
import { POST as approve } from "@/app/api/review/items/[id]/approve/route";
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

const request = (path: string, method = "GET", body?: unknown) =>
  new Request(`http://app.test${path}`, { method, body: body === undefined ? undefined : JSON.stringify(body), headers: { "content-type": "application/json" } });
const params = <T extends object>(value: T) => ({ params: Promise.resolve(value) });
const last = () => {
  const call = calls.at(-1) as Call;
  return { url: call.url, method: call.init.method ?? "GET", body: call.init.body, auth: new Headers(call.init.headers).get("authorization") };
};

describe("conversation routes", () => {
  it("lists and searches with the session's token, passing the query on", async () => {
    await signedIn();
    replies.push(Response.json([{ id: "c1" }]), Response.json([]));

    const listed = await list(request("/api/conversations?limit=200"));
    expect(await listed.json()).toEqual([{ id: "c1" }]);
    expect(last()).toMatchObject({ url: "http://api:8000/conversations?limit=200", method: "GET", auth: "Bearer access-1" });

    await search(request("/api/conversations/search?q=doanh%20thu"));
    expect(last().url).toBe("http://api:8000/conversations/search?q=doanh%20thu");
  });

  it("reads, changes and deletes one conversation", async () => {
    await signedIn();
    replies.push(Response.json({ conversation: { id: "c 1" }, turns: [] }), Response.json({ id: "c 1" }), new Response(null, { status: 204 }));

    expect((await read(request("/api/conversations/c%201"), params({ id: "c 1" }))).status).toBe(200);
    expect(new URL(last().url).pathname).toBe("/conversations/c%201");
    await update(request("/api/conversations/c%201", "PATCH", { pinned: true }), params({ id: "c 1" }));
    expect(last()).toMatchObject({ method: "PATCH", body: JSON.stringify({ pinned: true }) });
    const deleted = await remove(request("/api/conversations/c%201", "DELETE"), params({ id: "c 1" }));
    expect(deleted.status).toBe(204);
    expect(last().method).toBe("DELETE");
  });

  it("manages groups", async () => {
    await signedIn();
    replies.push(Response.json([]), Response.json({ id: "g1", name: "Sales" }, { status: 201 }), Response.json({ id: "g1", name: "S" }),
      new Response(null, { status: 204 }));

    await groups(request("/api/conversation-groups"));
    const created = await createGroup(request("/api/conversation-groups", "POST", { name: "Sales" }));
    expect(created.status).toBe(201);
    expect(last()).toMatchObject({ url: "http://api:8000/conversation-groups", method: "POST", body: JSON.stringify({ name: "Sales" }) });
    await renameGroup(request("/api/conversation-groups/g1", "PATCH", { name: "S" }), params({ id: "g1" }));
    expect(last()).toMatchObject({ url: "http://api:8000/conversation-groups/g1", method: "PATCH" });
    expect((await removeGroup(request("/api/conversation-groups/g1", "DELETE"), params({ id: "g1" }))).status).toBe(204);
  });

  it("passes the api's 404 through", async () => {
    await signedIn();
    replies.push(Response.json({ detail: "conversation not found" }, { status: 404 }));

    const response = await read(request("/api/conversations/theirs"), params({ id: "theirs" }));

    expect(response.status).toBe(404);
    expect(await response.json()).toEqual({ detail: "conversation not found" });
  });

  it("forwards feedback with the session's token and passes the api's 404 for another user's answer through", async () => {
    await signedIn();
    replies.push(new Response(null, { status: 204 }), Response.json({ detail: "answer not found" }, { status: 404 }));
    const body = { trace_id: "t".repeat(32), rating: "dislike", note: "Wrong quarter" };

    expect((await feedback(request("/api/feedback", "POST", body))).status).toBe(204);
    expect(last()).toMatchObject({ url: "http://api:8000/feedback", method: "POST", body: JSON.stringify(body), auth: "Bearer access-1" });
    expect((await feedback(request("/api/feedback", "POST", { ...body, trace_id: "theirs" }))).status).toBe(404);
  });

  it("is a 401 without a session and never calls the api", async () => {
    expect((await list(request("/api/conversations"))).status).toBe(401);
    expect(calls).toEqual([]);
  });
});


describe("onboarding routes", () => {
  it("forwards a multipart upload with its own content type and the session's token", async () => {
    await signedIn();
    replies.push(Response.json({ id: "d1" }, { status: 201 }));
    const form = new FormData();
    form.append("file", new File(["# Notes"], "notes.md"));
    form.append("allowed_roles", "analyst");
    const incoming = new Request("http://app.test/api/documents", { method: "POST", body: form });

    const response = await upload(incoming);

    expect(response.status).toBe(201);
    const call = calls.at(-1) as Call;
    expect(call.url).toBe("http://api:8000/documents");
    expect(new Headers(call.init.headers).get("content-type")).toMatch(/^multipart\/form-data; boundary=/);
    expect(new TextDecoder().decode(call.init.body as ArrayBuffer)).toContain('name="allowed_roles"');
    expect(new Headers(call.init.headers).get("authorization")).toBe("Bearer access-1");
  });

  it("passes the review filters on and names the item in approve and draft paths", async () => {
    await signedIn();
    replies.push(Response.json([]), Response.json({ id: "metrics.x" }), Response.json({ added: [] }));

    await reviewItems(request("/api/review/items?file=metrics.yaml&status=draft"));
    expect(last().url).toBe("http://api:8000/review/items?file=metrics.yaml&status=draft");
    await approve(request("/api/review/items/metrics.x/approve", "POST", {}), params({ id: "metrics.x" }));
    expect(last()).toMatchObject({ url: "http://api:8000/review/items/metrics.x/approve", method: "POST" });
    await draft(request("/api/documents/d%201/draft", "POST", {}), params({ id: "d 1" }));
    expect(last().url).toBe("http://api:8000/documents/d%201/draft");
  });
});
