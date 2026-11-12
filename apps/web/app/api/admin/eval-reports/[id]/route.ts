// One eval report, from the api's GET /admin/eval-reports/{id}.

import { forwardJson } from "@/lib/server/api";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

type Params = { params: Promise<{ id: string }> };

export async function GET(request: Request, { params }: Params): Promise<Response> {
  const { id } = await params;
  return forwardJson(request, `/admin/eval-reports/${encodeURIComponent(id)}`);
}
