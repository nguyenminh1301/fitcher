// The recent syncs of a source, forwarded to the api's GET /sources/{id}/syncs (admin only).

import { forwardJson } from "@/lib/server/api";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

type Params = { params: Promise<{ id: string }> };

export async function GET(request: Request, { params }: Params): Promise<Response> {
  const { id } = await params;
  return forwardJson(request, `/sources/${encodeURIComponent(id)}/syncs`);
}
