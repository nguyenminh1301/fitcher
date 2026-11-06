// Runs of the active pack, from the api's GET /admin/runs (admin).

import { forwardJson } from "@/lib/server/api";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(request: Request): Promise<Response> {
  return forwardJson(request, `/admin/runs` + new URL(request.url).search);
}
