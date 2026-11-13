// Calls from the web server to the fitcher api. The api keeps each sign-in: this server forwards the
// browser's session cookie and passes the api's Set-Cookie back, and keeps no session of its own.

import { cookies, headers as requestHeaders } from "next/headers";

/** The api's session cookie (app/auth/principal.py), HttpOnly and SameSite=Strict. */
export const SESSION_COOKIE = "fitcher_session";

export function apiBase(env: Record<string, string | undefined> = process.env): string {
  return (env.API_URL ?? "http://127.0.0.1:8000").replace(/\/+$/, "");
}

export function jsonError(error: string, status: number): Response {
  return Response.json({ error }, { status, headers: { "cache-control": "no-store" } });
}

/** Forward a JSON request to the api path as the signed-in user and pass its answer back unchanged. */
export async function forwardJson(request: Request, path: string): Promise<Response> {
  const body = request.method === "GET" || request.method === "DELETE" ? undefined : await request.text();
  const response = await callApi(path, {
    method: request.method, body, headers: body === undefined ? undefined : { "content-type": "application/json" },
  });
  if (response.status === 204) return new Response(null, { status: 204 });
  return new Response(response.body, {
    status: response.status, headers: { "content-type": "application/json", "cache-control": "no-store" },
  });
}

/**
 * Forward a request body as it came, with its own content type (a multipart upload), and pass the api's
 * JSON answer back unchanged.
 */
export async function forwardBody(request: Request, path: string): Promise<Response> {
  const contentType = request.headers.get("content-type");
  const response = await callApi(path, {
    method: request.method, body: await request.arrayBuffer(),
    headers: contentType ? { "content-type": contentType } : undefined,
  });
  return new Response(response.body, {
    status: response.status, headers: { "content-type": "application/json", "cache-control": "no-store" },
  });
}

/**
 * The browser's own host and origin for the api's address checks (individual mode): the api sees this
 * server as its client, so the browser's Host travels as X-Forwarded-Host. A forwarded host the client
 * sent is ignored, because a page can set that header on its own requests. A proxy's X-Forwarded-Proto
 * is passed on; the api trusts it only when the instance lists its public hosts.
 */
export function browserHeaders(incoming: Headers): Headers {
  const forwarded = new Headers();
  const host = incoming.get("host");
  const origin = incoming.get("origin");
  const proto = incoming.get("x-forwarded-proto");
  if (host) forwarded.set("x-forwarded-host", host);
  if (origin) forwarded.set("origin", origin);
  if (proto) forwarded.set("x-forwarded-proto", proto);
  return forwarded;
}

/**
 * Send a request to the api as the browser's session, or as the owner in individual mode, which needs
 * none. A 401 from the api becomes the web's ``signed_out`` answer.
 */
export async function callApi(path: string, init: RequestInit = {}): Promise<Response> {
  const response = await rawApi(path, init);
  if (response.status === 401) return jsonError("signed_out", 401);
  return response;
}

/** Send a request to the api with the browser's session cookie and address headers, unchanged otherwise. */
export async function rawApi(path: string, init: RequestInit = {}): Promise<Response> {
  const headers = new Headers(init.headers);
  for (const [name, value] of browserHeaders(await requestHeaders())) headers.set(name, value);
  const session = (await cookies()).get(SESSION_COOKIE)?.value;
  if (session) headers.set("cookie", `${SESSION_COOKIE}=${session}`);
  try {
    return await fetch(`${apiBase()}${path}`, { ...init, headers, cache: "no-store" });
  } catch {
    return jsonError("api_unreachable", 502);
  }
}

const PASSED_HEADERS = ["content-type", "location", "retry-after"];

/** The api's answer as the browser gets it: status, body, its cookies and the headers that matter. */
export function passThrough(response: Response): Response {
  const headers = new Headers({ "cache-control": "no-store" });
  for (const name of PASSED_HEADERS) {
    const value = response.headers.get(name);
    if (value) headers.set(name, value);
  }
  for (const cookie of response.headers.getSetCookie()) headers.append("set-cookie", cookie);
  const empty = response.status === 204 || response.status === 304 || (response.status >= 300 && response.status < 400);
  return new Response(empty ? null : response.body, { status: response.status, headers });
}
