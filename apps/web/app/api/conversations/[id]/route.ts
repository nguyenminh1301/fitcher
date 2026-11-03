// One conversation of the signed-in user: its thread, a rename, pin or move, and delete.

import { forwardJson } from "@/lib/server/api";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

type Params = { params: Promise<{ id: string }> };

async function forward(request: Request, { params }: Params): Promise<Response> {
  const { id } = await params;
  return forwardJson(request, `/conversations/${encodeURIComponent(id)}`);
}

export const GET = forward;
export const PATCH = forward;
export const DELETE = forward;
