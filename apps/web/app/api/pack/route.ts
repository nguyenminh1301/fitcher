// The active pack's name, display name and roles from the api's GET /pack, with the browser's session and
// address headers like every other route.

import { rawApi } from "@/lib/server/api";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(): Promise<Response> {
  const response = await rawApi("/pack", { cache: "no-store" });
  return new Response(response.body, { status: response.status, headers: { "content-type": "application/json", "cache-control": "no-store" } });
}
