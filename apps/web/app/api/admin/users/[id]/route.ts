// Change one account's display name, roles or status, forwarded to the api's PATCH /admin/users/{id} (admin).

import { forwardJson } from "@/lib/server/api";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

type Params = { params: Promise<{ id: string }> };

export async function PATCH(request: Request, { params }: Params): Promise<Response> {
  const { id } = await params;
  return forwardJson(request, `/admin/users/${encodeURIComponent(id)}`);
}
