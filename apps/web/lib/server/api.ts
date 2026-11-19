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

const MIB = 1024 * 1024;

/** The largest JSON body a route handler reads: questions, settings and passwords are far smaller. */
export const JSON_BODY_MAX_BYTES = MIB;

/** Room for the multipart boundaries and part headers around an uploaded file. */
const MULTIPART_SLACK_BYTES = MIB;

/**
 * The largest multipart upload the web server forwards: the api's own file limit (the same environment
 * variable and default the api reads) plus the multipart framing around the file.
 */
export function uploadLimit(name: "SOURCE_FILE_MAX_BYTES" | "DOCUMENT_MAX_BYTES",
  env: Record<string, string | undefined> = process.env): number {
  const fallback = name === "SOURCE_FILE_MAX_BYTES" ? 256 * MIB : 20 * MIB;
  const value = Number(env[name]);
  return (Number.isSafeInteger(value) && value > 0 ? value : fallback) + MULTIPART_SLACK_BYTES;
}

/** A request body over its route's limit. */
export class BodyTooLarge extends Error {
  constructor() {
    super("body_too_large");
  }
}

export function bodyTooLarge(): Response {
  return jsonError("body_too_large", 413);
}

function declaredOver(request: Request, limit: number): boolean {
  const length = Number(request.headers.get("content-length"));
  return Number.isFinite(length) && length > limit;
}

/**
 * The request body as text, refused with BodyTooLarge before reading when its declared length is over
 * `limit`, and as soon as more than `limit` bytes arrived when it is sent without one (chunked).
 */
export async function readBody(request: Request, limit: number = JSON_BODY_MAX_BYTES): Promise<string> {
  if (declaredOver(request, limit)) throw new BodyTooLarge();
  if (!request.body) return "";
  const reader = request.body.getReader();
  const chunks: Uint8Array[] = [];
  let size = 0;
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    size += value.byteLength;
    if (size > limit) {
      await reader.cancel();
      throw new BodyTooLarge();
    }
    chunks.push(value);
  }
  const bytes = new Uint8Array(size);
  let offset = 0;
  for (const chunk of chunks) {
    bytes.set(chunk, offset);
    offset += chunk.byteLength;
  }
  return new TextDecoder().decode(bytes);
}

/** The request body as JSON text, or the web's 413 answer when it is over the JSON limit. */
export async function readJsonBody(request: Request): Promise<string | Response> {
  try {
    return await readBody(request);
  } catch (error) {
    if (error instanceof BodyTooLarge) return bodyTooLarge();
    throw error;
  }
}

/** Forward a JSON request to the api path as the signed-in user and pass its answer back unchanged. */
export async function forwardJson(request: Request, path: string): Promise<Response> {
  let body: string | undefined;
  if (request.method !== "GET" && request.method !== "DELETE") {
    const read = await readJsonBody(request);
    if (read instanceof Response) return read;
    body = read;
  }
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
 * JSON answer back unchanged. The body is streamed to the api, never held in memory: a declared length over
 * `limit` is refused before reading, and a body sent without one is cut off once it passes `limit`.
 */
export async function forwardBody(request: Request, path: string, limit: number): Promise<Response> {
  if (declaredOver(request, limit)) return bodyTooLarge();
  const contentType = request.headers.get("content-type");
  let size = 0;
  let exceeded = false;
  const body = request.body?.pipeThrough(new TransformStream<Uint8Array, Uint8Array>({
    transform(chunk, controller) {
      size += chunk.byteLength;
      if (size > limit) {
        exceeded = true;
        controller.error(new BodyTooLarge());
      } else {
        controller.enqueue(chunk);
      }
    },
  }));
  // A streamed request body needs half duplex, which RequestInit's type does not list yet.
  const init = { method: request.method, body: body ?? null, duplex: "half",
    headers: contentType ? { "content-type": contentType } : undefined } as RequestInit;
  const response = await callApi(path, init);
  if (exceeded) return bodyTooLarge();
  return new Response(response.body, {
    status: response.status, headers: { "content-type": "application/json", "cache-control": "no-store" },
  });
}

/**
 * The browser's own host and origin for the api's address checks (individual mode): the api sees this
 * server as its client, so the browser's Host travels as X-Forwarded-Host. A forwarded host the client
 * sent is ignored, because a page can set that header on its own requests. X-Fitcher-Peer is the address
 * of the browser's connection, which peer-address.cjs writes over any value the client sent, so the api
 * refuses a loopback Host claimed from another machine. X-Fitcher-Proxy, written by the same hook, lists the
 * signs that a reverse proxy relayed the request, so the api never takes a proxied request for this computer.
 * A proxy's X-Forwarded-Proto and X-Forwarded-For are passed on; the api trusts the first only when the instance
 * lists its public hosts, and the second only from an address in FITCHER_TRUSTED_PROXIES.
 */
export function browserHeaders(incoming: Headers): Headers {
  const forwarded = new Headers();
  const host = incoming.get("host");
  const origin = incoming.get("origin");
  const proto = incoming.get("x-forwarded-proto");
  const client = incoming.get("x-forwarded-for");
  const peer = incoming.get("x-fitcher-peer");
  const proxy = incoming.get("x-fitcher-proxy");
  if (host) forwarded.set("x-forwarded-host", host);
  if (peer !== null) forwarded.set("x-fitcher-peer", peer);
  if (proxy !== null) forwarded.set("x-fitcher-proxy", proxy);
  if (origin) forwarded.set("origin", origin);
  if (proto) forwarded.set("x-forwarded-proto", proto);
  if (client) forwarded.set("x-forwarded-for", client);
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
