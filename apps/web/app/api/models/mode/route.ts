// How the tiers' chains are chosen (manual, auto_free or auto_best), forwarded to the api's PUT /models/mode
// (admin only).

import { forwardJson } from "@/lib/server/api";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function PUT(request: Request): Promise<Response> {
  return forwardJson(request, "/models/mode");
}
