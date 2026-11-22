// The model providers, forwarded to the api's GET and POST /providers (admin only). A key goes to the api
// once and never comes back: responses carry only whether it is set and its last four characters.

import { forwardJson } from "@/lib/server/api";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(request: Request): Promise<Response> {
  return forwardJson(request, "/providers");
}

export async function POST(request: Request): Promise<Response> {
  return forwardJson(request, "/providers");
}
