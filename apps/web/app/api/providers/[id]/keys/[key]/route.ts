// Removing one API key of a provider, forwarded to the api's DELETE /providers/{id}/keys/{key} (admin only).

import { forwardJson } from "@/lib/server/api";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

type Params = { params: Promise<{ id: string; key: string }> };

export async function DELETE(request: Request, { params }: Params): Promise<Response> {
  const { id, key } = await params;
  return forwardJson(request, `/providers/${encodeURIComponent(id)}/keys/${encodeURIComponent(key)}`);
}
