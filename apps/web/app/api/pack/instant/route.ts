// Start an instant pack, forwarded to the api's POST /pack/instant (admin only; the draft is a paid call).

import { forwardJson } from "@/lib/server/api";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function POST(request: Request): Promise<Response> {
  return forwardJson(request, "/pack/instant");
}
