// A provider's model catalog, forwarded to the api's GET /models/catalog?provider= (admin only).

import { forwardJson } from "@/lib/server/api";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(request: Request): Promise<Response> {
  return forwardJson(request, "/models/catalog" + new URL(request.url).search);
}
