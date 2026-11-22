// Test a connection without saving it, forwarded to the api's POST /sources/test (admin only).

import { forwardJson } from "@/lib/server/api";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function POST(request: Request): Promise<Response> {
  return forwardJson(request, "/sources/test");
}
