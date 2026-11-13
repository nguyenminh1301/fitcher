// The model tiers and the embedding, forwarded to the api's GET /models/tiers (admin only).

import { forwardJson } from "@/lib/server/api";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(request: Request): Promise<Response> {
  return forwardJson(request, "/models/tiers");
}
