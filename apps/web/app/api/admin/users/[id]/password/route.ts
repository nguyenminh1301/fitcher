// Reset one account's password, forwarded to the api's POST /admin/users/{id}/password (admin).

import { forwardJson } from "@/lib/server/api";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

type Params = { params: Promise<{ id: string }> };

export async function POST(request: Request, { params }: Params): Promise<Response> {
  const { id } = await params;
  return forwardJson(request, `/admin/users/${encodeURIComponent(id)}/password`);
}
