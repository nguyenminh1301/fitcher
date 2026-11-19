// Signing in with the owner password and out again (DECISIONS §9): the api's session cookie passes through.

import { passThrough, rawApi, readJsonBody } from "@/lib/server/api";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function POST(request: Request): Promise<Response> {
  const body = await readJsonBody(request);
  if (body instanceof Response) return body;
  return passThrough(await rawApi("/owner/session", { method: "POST", body, headers: { "content-type": "application/json" } }));
}

export async function DELETE(): Promise<Response> {
  return passThrough(await rawApi("/owner/session", { method: "DELETE" }));
}
