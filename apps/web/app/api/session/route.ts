// Who is signed in, as the api's GET /me reports it for the session's access token; 401 when signed out.

import { callApi, jsonError } from "@/lib/server/api";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

type Me = { user_id: string; display_name: string; roles: string[] };

export async function GET(): Promise<Response> {
  const response = await callApi("/me");
  if (!response.ok) return response.headers.get("content-type")?.includes("json") ? response : jsonError("api_error", response.status);
  const me = (await response.json()) as Me;
  return Response.json({ user_id: me.user_id, display_name: me.display_name, roles: me.roles }, { headers: { "cache-control": "no-store" } });
}
