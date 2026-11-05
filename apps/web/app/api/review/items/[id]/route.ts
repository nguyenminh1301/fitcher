// Edit or delete one pack item, forwarded to the api's PATCH and DELETE /review/items/{id} (pack_reviewer).

import { forwardJson } from "@/lib/server/api";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

type Params = { params: Promise<{ id: string }> };

async function forward(request: Request, { params }: Params): Promise<Response> {
  const { id } = await params;
  return forwardJson(request, `/review/items/${encodeURIComponent(id)}`);
}

export const PATCH = forward;
export const DELETE = forward;
