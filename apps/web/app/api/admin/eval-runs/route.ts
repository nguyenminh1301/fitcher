// Start an eval run (paid AI), forwarded to the api's POST /admin/eval-runs (admin).

import { forwardJson } from "@/lib/server/api";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function POST(request: Request): Promise<Response> {
  return forwardJson(request, `/admin/eval-runs`);
}
