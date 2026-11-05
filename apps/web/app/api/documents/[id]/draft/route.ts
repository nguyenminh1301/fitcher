// Draft pack items from one document (paid AI), forwarded to the api's POST /documents/{id}/draft.

import { forwardJson } from "@/lib/server/api";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

type Params = { params: Promise<{ id: string }> };

export async function POST(request: Request, { params }: Params): Promise<Response> {
  const { id } = await params;
  return forwardJson(request, `/documents/${encodeURIComponent(id)}/draft`);
}
