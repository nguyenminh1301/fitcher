// A provider's test call, forwarded to the api's POST /providers/{id}/test (admin only); a hosted provider bills it.

import { forwardJson } from "@/lib/server/api";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

type Params = { params: Promise<{ id: string }> };

export async function POST(request: Request, { params }: Params): Promise<Response> {
  const { id } = await params;
  return forwardJson(request, `/providers/${encodeURIComponent(id)}/test`);
}
