// The active pack's name, display name and roles from the api's public GET /pack, for the sign-in screen.

import { apiBase, jsonError } from "@/lib/server/api";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(): Promise<Response> {
  try {
    const response = await fetch(`${apiBase()}/pack`, { cache: "no-store" });
    return new Response(response.body, { status: response.status, headers: { "content-type": "application/json", "cache-control": "no-store" } });
  } catch {
    return jsonError("api_unreachable", 502);
  }
}
