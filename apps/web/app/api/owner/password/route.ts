// Setting, changing and removing the owner password; setting it signs this browser in with a new cookie.

import { passThrough, rawApi, readJsonBody } from "@/lib/server/api";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

async function forward(request: Request, method: "PUT" | "DELETE"): Promise<Response> {
  const body = await readJsonBody(request);
  if (body instanceof Response) return body;
  return passThrough(await rawApi("/owner/password", { method, body, headers: { "content-type": "application/json" } }));
}

export async function PUT(request: Request): Promise<Response> {
  return forward(request, "PUT");
}

export async function DELETE(request: Request): Promise<Response> {
  return forward(request, "DELETE");
}
