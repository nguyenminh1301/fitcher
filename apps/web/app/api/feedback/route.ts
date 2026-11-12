// The signed-in user's like or dislike of one answer, forwarded to the api's POST /feedback.

import { forwardJson } from "@/lib/server/api";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function POST(request: Request): Promise<Response> {
  return forwardJson(request, "/feedback");
}
