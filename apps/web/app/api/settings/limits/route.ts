// How many questions the api answers at once (DECISIONS §15, Settings): GET reads the limit, PUT changes it.

import { forwardJson } from "@/lib/server/api";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(request: Request): Promise<Response> {
  return forwardJson(request, "/settings/limits");
}

export async function PUT(request: Request): Promise<Response> {
  return forwardJson(request, "/settings/limits");
}
