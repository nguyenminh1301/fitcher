// @vitest-environment node
import { NextRequest } from "next/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const jar = new Map<string, string>();
vi.mock("next/headers", () => ({
  headers: async () => new Headers({ host: "app.test", origin: "http://app.test" }),
  cookies: async () => ({ get: (name: string) => (jar.has(name) ? { name, value: jar.get(name) } : undefined) }),
}));

import { GET as session } from "@/app/api/session/route";

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

const ME = { user_id: "owner", display_name: "Owner", roles: ["viewer", "admin"], active_role: "viewer", exposed: false };

describe("session route", () => {
  it("answers who the api says the request acts as, with the browser's address headers", async () => {
    replies.push(Response.json(ME));

    const response = await session();

    expect(await response.json()).toEqual({ user_id: "owner", display_name: "Owner", roles: ["viewer", "admin"], exposed: false });
    expect(calls[0].url).toBe("http://api:8000/me");
    expect(calls[0].headers.get("authorization")).toBeNull();
    expect(calls[0].headers.get("x-forwarded-host")).toBe("app.test");
  });
});
