// The active pack's example questions for an empty chat, forwarded to the api's GET /pack/suggestions (signed in).

import { forwardJson } from "@/lib/server/api";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(request: Request): Promise<Response> {
  return forwardJson(request, "/pack/suggestions");
}
