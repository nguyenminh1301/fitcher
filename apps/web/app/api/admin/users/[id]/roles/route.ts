// Set one user's pack roles, forwarded to the api's PUT /admin/users/{id}/roles (admin).

import { forwardJson } from "@/lib/server/api";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

type Params = { params: Promise<{ id: string }> };

export async function PUT(request: Request, { params }: Params): Promise<Response> {
  const { id } = await params;
  return forwardJson(request, `/admin/users/${encodeURIComponent(id)}/roles`);
}
