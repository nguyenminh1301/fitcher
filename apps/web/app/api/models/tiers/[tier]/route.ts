// One chat tier's model, forwarded to the api's PUT /models/tiers/{tier} (admin only).

import { forwardJson } from "@/lib/server/api";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

type Params = { params: Promise<{ tier: string }> };

export async function PUT(request: Request, { params }: Params): Promise<Response> {
  const { tier } = await params;
  return forwardJson(request, `/models/tiers/${encodeURIComponent(tier)}`);
}
