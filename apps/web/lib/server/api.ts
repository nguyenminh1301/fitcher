// Calls from the web server to the fitcher api, with the signed-in user's access token.

import { cookies } from "next/headers";

import { SESSION_COOKIE, accessToken, authConfig, dropSession } from "./auth";

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
 * Send a request to the api as the signed-in user. Without a session, or when the api refuses the
 * token, the user is signed out and the answer is a 401.
 */
export async function callApi(path: string, init: RequestInit = {}): Promise<Response> {
  const session = (await cookies()).get(SESSION_COOKIE)?.value;
  const token = await accessToken(authConfig(), session);
  if (!token) return jsonError("signed_out", 401);
  const headers = new Headers(init.headers);
  headers.set("authorization", `Bearer ${token}`);
  let response: Response;
  try {
    response = await fetch(`${apiBase()}${path}`, { ...init, headers, cache: "no-store" });
  } catch {
    return jsonError("api_unreachable", 502);
  }
  if (response.status === 401) {
    dropSession(session);
    return jsonError("signed_out", 401);
  }
  return response;
}
