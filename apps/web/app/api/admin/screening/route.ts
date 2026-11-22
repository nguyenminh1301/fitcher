// Recent input-screening verdicts without the screened text, from the api's GET /admin/screening (admin).

import { forwardJson } from "@/lib/server/api";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(request: Request): Promise<Response> {
  return forwardJson(request, `/admin/screening` + new URL(request.url).search);
}
