// Forwards to the api's GET /setup/status as the signed-in user (the changes need the admin role).

import { forwardJson } from "@/lib/server/api";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(request: Request): Promise<Response> {
  return forwardJson(request, "/setup/status");
}
