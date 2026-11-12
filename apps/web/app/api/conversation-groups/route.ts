// The signed-in user's conversation groups: list and create.

import { forwardJson } from "@/lib/server/api";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(request: Request): Promise<Response> {
  return forwardJson(request, "/conversation-groups");
}

export async function POST(request: Request): Promise<Response> {
  return forwardJson(request, "/conversation-groups");
}
