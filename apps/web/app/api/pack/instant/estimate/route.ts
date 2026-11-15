// The prompt size of an instant pack's draft, forwarded to the api's POST /pack/instant/estimate (admin only).

import { forwardJson } from "@/lib/server/api";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function POST(request: Request): Promise<Response> {
  return forwardJson(request, "/pack/instant/estimate");
}
