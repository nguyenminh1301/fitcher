// The steps and result of an instant pack job, forwarded to the api's GET /pack/instant/{job} (admin only).

import { forwardJson } from "@/lib/server/api";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

type Params = { params: Promise<{ job: string }> };

export async function GET(request: Request, { params }: Params): Promise<Response> {
  const { job } = await params;
  return forwardJson(request, `/pack/instant/${encodeURIComponent(job)}`);
}
