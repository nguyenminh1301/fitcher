// One provider, forwarded to the api's PATCH and DELETE /providers/{id} (admin only).

import { forwardJson } from "@/lib/server/api";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

type Params = { params: Promise<{ id: string }> };

export async function PATCH(request: Request, { params }: Params): Promise<Response> {
  const { id } = await params;
  return forwardJson(request, `/providers/${encodeURIComponent(id)}`);
}

export async function DELETE(request: Request, { params }: Params): Promise<Response> {
  const { id } = await params;
  return forwardJson(request, `/providers/${encodeURIComponent(id)}`);
}
