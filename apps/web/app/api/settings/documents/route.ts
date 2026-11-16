// Company documents on or off (DECISIONS §15): GET is readable by any signed-in user so the console can hide
// the Documents page, and PUT forwards to the api, which needs the admin role.

import { forwardJson } from "@/lib/server/api";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(request: Request): Promise<Response> {
  return forwardJson(request, "/settings/documents");
}

export async function PUT(request: Request): Promise<Response> {
  return forwardJson(request, "/settings/documents");
}
