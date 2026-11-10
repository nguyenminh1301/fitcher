// One run's trace, from the api's GET /admin/runs/{trace_id} (admin).

import { forwardJson } from "@/lib/server/api";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

type Params = { params: Promise<{ traceId: string }> };

export async function GET(request: Request, { params }: Params): Promise<Response> {
  const { traceId } = await params;
  return forwardJson(request, `/admin/runs/${encodeURIComponent(traceId)}`);
}
