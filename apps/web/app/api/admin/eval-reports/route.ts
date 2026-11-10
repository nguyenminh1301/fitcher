// Eval reports, from the api's GET /admin/eval-reports (pack_reviewer or admin).

import { forwardJson } from "@/lib/server/api";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(request: Request): Promise<Response> {
  return forwardJson(request, `/admin/eval-reports` + new URL(request.url).search);
}
