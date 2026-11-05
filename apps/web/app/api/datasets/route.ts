// The compiled pack's datasets for the console's Datasets page, from the api's GET /datasets (pack_reviewer).

import { forwardJson } from "@/lib/server/api";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(request: Request): Promise<Response> {
  return forwardJson(request, "/datasets");
}
