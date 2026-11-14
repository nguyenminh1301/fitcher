// A source's tables, forwarded to the api's GET and PUT /sources/{id}/tables (admin only); GET may ask
// for a refresh of the catalog.

import { forwardJson } from "@/lib/server/api";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

type Params = { params: Promise<{ id: string }> };

export async function GET(request: Request, { params }: Params): Promise<Response> {
  const { id } = await params;
  return forwardJson(request, `/sources/${encodeURIComponent(id)}/tables${new URL(request.url).search}`);
}

export async function PUT(request: Request, { params }: Params): Promise<Response> {
  const { id } = await params;
  return forwardJson(request, `/sources/${encodeURIComponent(id)}/tables`);
}
