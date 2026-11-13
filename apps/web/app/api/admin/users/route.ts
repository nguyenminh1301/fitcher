// Accounts with their pack and console roles: GET lists them and POST creates one, through the api's
// /admin/users (admin).

import { forwardJson } from "@/lib/server/api";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(request: Request): Promise<Response> {
  return forwardJson(request, `/admin/users` + new URL(request.url).search);
}

export async function POST(request: Request): Promise<Response> {
  return forwardJson(request, "/admin/users");
}
