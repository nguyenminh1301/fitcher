// Search the signed-in user's conversation titles and questions through the api.

import { forwardJson } from "@/lib/server/api";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(request: Request): Promise<Response> {
  return forwardJson(request, `/conversations/search${new URL(request.url).search}`);
}
