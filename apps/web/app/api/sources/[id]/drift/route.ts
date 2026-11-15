// Columns changed since the source's instant pack was built, forwarded to the api's GET /sources/{id}/drift
// (admin only); it may ask for the catalog to be read again.

import { forwardJson } from "@/lib/server/api";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

type Params = { params: Promise<{ id: string }> };

export async function GET(request: Request, { params }: Params): Promise<Response> {
  const { id } = await params;
  return forwardJson(request, `/sources/${encodeURIComponent(id)}/drift${new URL(request.url).search}`);
}
