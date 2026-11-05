// The pack items of the console's Review page, from the api's GET /review/items (pack_reviewer).

import { forwardJson } from "@/lib/server/api";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(request: Request): Promise<Response> {
  return forwardJson(request, `/review/items${new URL(request.url).search}`);
}
