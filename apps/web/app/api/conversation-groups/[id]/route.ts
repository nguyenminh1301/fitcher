// One conversation group of the signed-in user: rename and delete.

import { forwardJson } from "@/lib/server/api";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

type Params = { params: Promise<{ id: string }> };

async function forward(request: Request, { params }: Params): Promise<Response> {
  const { id } = await params;
  return forwardJson(request, `/conversation-groups/${encodeURIComponent(id)}`);
}

export const PATCH = forward;
export const DELETE = forward;
