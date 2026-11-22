// The active pack's name, display name and roles from the api's GET /pack, and PUT /pack to make another
// compiled pack the current one, with the browser's session and address headers like every other route.

import { forwardJson, rawApi } from "@/lib/server/api";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(): Promise<Response> {
  const response = await rawApi("/pack", { cache: "no-store" });
  return new Response(response.body, { status: response.status, headers: { "content-type": "application/json", "cache-control": "no-store" } });
}

export async function PUT(request: Request): Promise<Response> {
  return forwardJson(request, "/pack");
}
