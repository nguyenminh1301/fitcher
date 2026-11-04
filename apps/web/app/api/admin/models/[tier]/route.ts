// A change of one chat tier's alias, forwarded to the api's PUT /admin/models/{tier} (admin only).

import { forwardJson } from "@/lib/server/api";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

type Params = { params: Promise<{ tier: string }> };

export async function PUT(request: Request, { params }: Params): Promise<Response> {
  const { tier } = await params;
  return forwardJson(request, `/admin/models/${encodeURIComponent(tier)}`);
}
