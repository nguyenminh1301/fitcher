// Propose an example from one run, forwarded to the api (pack_reviewer).

import { forwardJson } from "@/lib/server/api";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

type Params = { params: Promise<{ traceId: string }> };

export async function POST(request: Request, { params }: Params): Promise<Response> {
  const { traceId } = await params;
  return forwardJson(request, `/admin/feedback/${encodeURIComponent(traceId)}/proposal`);
}
