// Load an uploaded file with the confirmed column types, forwarded to the api's POST /sources/files/{id}/load.

import { forwardJson } from "@/lib/server/api";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

type Params = { params: Promise<{ id: string }> };

export async function POST(request: Request, { params }: Params): Promise<Response> {
  const { id } = await params;
  return forwardJson(request, `/sources/files/${encodeURIComponent(id)}/load`);
}
