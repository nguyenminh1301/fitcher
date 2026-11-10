// Likes and dislikes, from the api's GET /admin/feedback (pack_reviewer).

import { forwardJson } from "@/lib/server/api";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(request: Request): Promise<Response> {
  return forwardJson(request, `/admin/feedback` + new URL(request.url).search);
}
