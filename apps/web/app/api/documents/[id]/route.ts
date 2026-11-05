// Change one document's roles or delete it, forwarded to the api's PATCH and DELETE /documents/{id}.

import { forwardJson } from "@/lib/server/api";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

type Params = { params: Promise<{ id: string }> };

async function forward(request: Request, { params }: Params): Promise<Response> {
  const { id } = await params;
  return forwardJson(request, `/documents/${encodeURIComponent(id)}`);
}

export const PATCH = forward;
export const DELETE = forward;
