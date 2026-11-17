// Signing in with the owner password and out again (DECISIONS §9): the api's session cookie passes through.

import { passThrough, rawApi } from "@/lib/server/api";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function POST(request: Request): Promise<Response> {
  return passThrough(await rawApi("/owner/session", {
    method: "POST", body: await request.text(), headers: { "content-type": "application/json" },
  }));
}

export async function DELETE(): Promise<Response> {
  return passThrough(await rawApi("/owner/session", { method: "DELETE" }));
}
