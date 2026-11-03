// The chat's /ask stream: the question goes to the api with the session's access token and the api's
// server-sent events come back unchanged. When the browser stops reading (Stop, or the page closes), the
// request to the api is aborted too, so the api stops the run.

import { callApi, jsonError } from "@/lib/server/api";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function POST(request: Request): Promise<Response> {
  let body: string;
  try {
    body = JSON.stringify(await request.json());
  } catch {
    return jsonError("invalid_request", 400);
  }
  const response = await callApi("/ask", { method: "POST", body, headers: { "content-type": "application/json" }, signal: request.signal });
  if (!response.ok || !response.body) return response;
  return new Response(response.body, {
    headers: { "content-type": "text/event-stream", "cache-control": "no-cache, no-transform", "x-accel-buffering": "no" },
  });
}
