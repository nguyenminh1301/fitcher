// Test-run one pack item's formula, forwarded to the api's POST /review/items/{id}/test-run (pack_reviewer).

import { forwardJson } from "@/lib/server/api";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

type Params = { params: Promise<{ id: string }> };

export async function POST(request: Request, { params }: Params): Promise<Response> {
  const { id } = await params;
  return forwardJson(request, `/review/items/${encodeURIComponent(id)}/test-run`);
}
