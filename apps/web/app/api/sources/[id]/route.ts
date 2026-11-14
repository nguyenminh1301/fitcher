// One source, forwarded to the api's PATCH and DELETE /sources/{id} (admin only). A deletion carries its
// confirmation in the query string.

import { forwardJson } from "@/lib/server/api";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

type Params = { params: Promise<{ id: string }> };

export async function PATCH(request: Request, { params }: Params): Promise<Response> {
  const { id } = await params;
  return forwardJson(request, `/sources/${encodeURIComponent(id)}`);
}

export async function DELETE(request: Request, { params }: Params): Promise<Response> {
  const { id } = await params;
  return forwardJson(request, `/sources/${encodeURIComponent(id)}${new URL(request.url).search}`);
}
