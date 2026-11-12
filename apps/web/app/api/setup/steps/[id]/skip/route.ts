// Forwards to the api's POST /setup/steps/{id}/skip as the signed-in user (admin).

import { forwardJson } from "@/lib/server/api";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

type Params = { params: Promise<{ id: string }> };

export async function POST(request: Request, { params }: Params): Promise<Response> {
  const { id } = await params;
  return forwardJson(request, `/setup/steps/${encodeURIComponent(id)}/skip`);
}
