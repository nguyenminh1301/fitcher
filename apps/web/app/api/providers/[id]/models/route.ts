// The models a provider lists, forwarded to the api's GET /providers/{id}/models (admin only).

import { forwardJson } from "@/lib/server/api";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

type Params = { params: Promise<{ id: string }> };

export async function GET(request: Request, { params }: Params): Promise<Response> {
  const { id } = await params;
  return forwardJson(request, `/providers/${encodeURIComponent(id)}/models`);
}
