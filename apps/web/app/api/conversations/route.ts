// The signed-in user's conversations, newest activity first, from the api's GET /conversations.

import { forwardJson } from "@/lib/server/api";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(request: Request): Promise<Response> {
  return forwardJson(request, `/conversations${new URL(request.url).search}`);
}
