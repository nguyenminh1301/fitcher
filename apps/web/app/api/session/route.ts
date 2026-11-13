// The browser's session, kept by the api: GET answers who the request acts as (the owner in individual
// mode), POST signs in with an e-mail and password, DELETE signs out. The api's cookie passes through.

import { callApi, jsonError, passThrough, rawApi } from "@/lib/server/api";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

type Me = { user_id: string; display_name: string; roles: string[]; mode: "individual" | "team"; exposed: boolean };

export async function GET(): Promise<Response> {
  const response = await callApi("/me");
  if (!response.ok) return response.headers.get("content-type")?.includes("json") ? response : jsonError("api_error", response.status);
  const me = (await response.json()) as Me;
  return Response.json(
    { user_id: me.user_id, display_name: me.display_name, roles: me.roles, mode: me.mode, exposed: me.exposed },
    { headers: { "cache-control": "no-store" } },
  );
}

export async function POST(request: Request): Promise<Response> {
  return passThrough(await rawApi("/session", {
    method: "POST", body: await request.text(), headers: { "content-type": "application/json" },
  }));
}

export async function DELETE(): Promise<Response> {
  return passThrough(await rawApi("/session", { method: "DELETE" }));
}
