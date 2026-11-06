// Estimated LLM costs, from the api's GET /admin/costs (admin).

import { forwardJson } from "@/lib/server/api";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(request: Request): Promise<Response> {
  return forwardJson(request, `/admin/costs` + new URL(request.url).search);
}
