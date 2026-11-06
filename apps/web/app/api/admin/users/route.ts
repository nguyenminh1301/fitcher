// Realm users with their pack roles, from the api's GET /admin/users (admin).

import { forwardJson } from "@/lib/server/api";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(request: Request): Promise<Response> {
  return forwardJson(request, `/admin/users` + new URL(request.url).search);
}
