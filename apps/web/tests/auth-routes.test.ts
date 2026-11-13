// @vitest-environment node
import { createHash } from "node:crypto";

import { NextRequest } from "next/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const jar = new Map<string, string>();
vi.mock("next/headers", () => ({ headers: async () => new Headers({ host: "app.test" }), cookies: async () => ({ get: (name: string) => (jar.has(name) ? { name, value: jar.get(name) } : undefined) }) }));

import { GET as callback } from "@/app/auth/callback/route";
import { GET as signIn } from "@/app/auth/sign-in/route";
import { POST as signOut } from "@/app/auth/sign-out/route";
import { GET as session } from "@/app/api/session/route";
import { LOGIN_COOKIE, SESSION_COOKIE, accessToken, authConfig } from "@/lib/server/auth";

const ENV = {
  KEYCLOAK_ISSUER: "http://sso.test/realms/lab",
  KEYCLOAK_BACKCHANNEL_URL: "http://keycloak:8080/realms/lab",
  KEYCLOAK_CLIENT_ID: "lab-web",
  APP_URL: "http://app.test",
  API_URL: "http://api:8000",
};

type Call = { url: string; body: URLSearchParams | null; headers: Headers };
let calls: Call[];
let replies: Response[];

beforeEach(() => {
  Object.assign(process.env, ENV);
  jar.clear();
  calls = [];
  replies = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init: RequestInit = {}) => {
    calls.push({ url, body: init.body instanceof URLSearchParams ? init.body : null, headers: new Headers(init.headers) });
    return replies.shift() ?? new Response("{}", { status: 500 });
  }));
});

afterEach(() => {
  for (const name of Object.keys(ENV)) delete process.env[name];
  vi.unstubAllGlobals();
});

const tokens = (overrides: Record<string, unknown> = {}) =>
  Response.json({ access_token: "access-1", refresh_token: "refresh-1", id_token: "id-1", expires_in: 300, refresh_expires_in: 1800, ...overrides });

function cookie(response: Response, name: string): string | undefined {
  const line = response.headers.getSetCookie().find((item) => item.startsWith(`${name}=`));
  return line?.split(";")[0].slice(name.length + 1);
}

async function signedIn(): Promise<string> {
  const start = signIn();
  const state = new URL(start.headers.get("location") as string).searchParams.get("state") as string;
  replies.push(tokens());
  const done = await callback(new NextRequest(`http://app.test/auth/callback?state=${state}&code=code-1`, { headers: { cookie: `${LOGIN_COOKIE}=${state}` } }));
  return cookie(done, SESSION_COOKIE) as string;
}

describe("sign-in routes", () => {
  it("sends the browser to the realm with a PKCE challenge and remembers the state in a cookie", () => {
    const response = signIn();

    const location = new URL(response.headers.get("location") as string);
    expect(`${location.origin}${location.pathname}`).toBe("http://sso.test/realms/lab/protocol/openid-connect/auth");
    expect(Object.fromEntries(location.searchParams)).toMatchObject({
      client_id: "lab-web", response_type: "code", scope: "openid", redirect_uri: "http://app.test/auth/callback", code_challenge_method: "S256",
    });
    const line = response.headers.getSetCookie().find((item) => item.startsWith(`${LOGIN_COOKIE}=`)) as string;
    expect(line).toContain(`${LOGIN_COOKIE}=${location.searchParams.get("state")}`);
    expect(line.toLowerCase()).toContain("httponly");
  });

  it("exchanges the code with the verifier of the challenge and starts a session", async () => {
    const start = new URL(signIn().headers.get("location") as string);
    const state = start.searchParams.get("state") as string;
    replies.push(tokens());

    const response = await callback(new NextRequest(`http://app.test/auth/callback?state=${state}&code=code-1`, { headers: { cookie: `${LOGIN_COOKIE}=${state}` } }));

    expect(response.headers.get("location")).toBe("http://app.test/");
    expect(calls[0].url).toBe("http://keycloak:8080/realms/lab/protocol/openid-connect/token");
    const form = calls[0].body as URLSearchParams;
    expect(form.get("grant_type")).toBe("authorization_code");
    expect(form.get("code")).toBe("code-1");
    expect(createHash("sha256").update(form.get("code_verifier") as string).digest("base64url")).toBe(start.searchParams.get("code_challenge"));
    const id = cookie(response, SESSION_COOKIE);
    expect(id).toBeTruthy();
    expect(await accessToken(authConfig(), id)).toBe("access-1");
  });

  it.each([
    ["a state that is not the browser's", (state: string) => `state=${state}&code=c`, "other-state"],
    ["a missing code", (state: string) => `state=${state}`, undefined],
  ])("refuses %s", async (_name, query, cookieState) => {
    const state = new URL(signIn().headers.get("location") as string).searchParams.get("state") as string;

    const response = await callback(new NextRequest(`http://app.test/auth/callback?${query(state)}`, { headers: { cookie: `${LOGIN_COOKIE}=${cookieState ?? state}` } }));

    expect(response.headers.get("location")).toBe("http://app.test/sign-in?error=sign_in_failed");
    expect(cookie(response, SESSION_COOKIE)).toBeUndefined();
    expect(calls).toEqual([]);
  });

  it("uses a state only once", async () => {
    const state = new URL(signIn().headers.get("location") as string).searchParams.get("state") as string;
    const request = () => new NextRequest(`http://app.test/auth/callback?state=${state}&code=c`, { headers: { cookie: `${LOGIN_COOKIE}=${state}` } });
    replies.push(tokens());
    await callback(request());

    const again = await callback(request());

    expect(again.headers.get("location")).toContain("error=sign_in_failed");
  });

  it("refreshes an access token about to expire and signs out when the refresh fails", async () => {
    const id = await signedIn();
    const later = Date.now() + 290 * 1000;
    replies.push(tokens({ access_token: "access-2", refresh_token: "refresh-2" }));

    expect(await accessToken(authConfig(), id, later)).toBe("access-2");
    expect(calls.at(-1)?.body?.get("refresh_token")).toBe("refresh-1");

    replies.push(new Response("{}", { status: 400 }));
    expect(await accessToken(authConfig(), id, later + 300 * 1000)).toBeNull();
    expect(await accessToken(authConfig(), id)).toBeNull();
  });

  it("signs out with the ID token as hint and returns to the sign-in page", async () => {
    const id = await signedIn();

    const response = signOut(new NextRequest("http://app.test/auth/sign-out", { method: "POST", headers: { cookie: `${SESSION_COOKIE}=${id}` } }));

    const url = new URL(((await response.json()) as { url: string }).url);
    expect(`${url.origin}${url.pathname}`).toBe("http://sso.test/realms/lab/protocol/openid-connect/logout");
    expect(url.searchParams.get("id_token_hint")).toBe("id-1");
    expect(url.searchParams.get("post_logout_redirect_uri")).toBe("http://app.test/sign-in");
    expect(await accessToken(authConfig(), id)).toBeNull();
  });
});

describe("session route", () => {
  it("answers who is signed in from the api with the session's access token", async () => {
    jar.set(SESSION_COOKIE, await signedIn());
    replies.push(Response.json({ user_id: "lab.viewer", display_name: "Lab Viewer", roles: ["viewer"], active_role: "viewer" }));

    const response = await session();

    expect(await response.json()).toEqual({ user_id: "lab.viewer", display_name: "Lab Viewer", roles: ["viewer"] });
    expect(calls.at(-1)?.url).toBe("http://api:8000/me");
    expect(calls.at(-1)?.headers.get("authorization")).toBe("Bearer access-1");
    expect(calls.at(-1)?.headers.get("x-forwarded-host")).toBe("app.test");
  });

  it("is a 401 without a session, and signs out when the api refuses the token", async () => {
    expect((await session()).status).toBe(401);

    const id = await signedIn();
    jar.set(SESSION_COOKIE, id);
    replies.push(Response.json({ detail: "invalid or expired access token" }, { status: 401 }));

    expect((await session()).status).toBe(401);
    expect(await accessToken(authConfig(), id)).toBeNull();
  });
});
