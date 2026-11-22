// The embedding model, forwarded to the api's PUT /models/embedding (admin only); it needs a confirmed reindex.

import { forwardJson } from "@/lib/server/api";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function PUT(request: Request): Promise<Response> {
  return forwardJson(request, "/models/embedding");
}
