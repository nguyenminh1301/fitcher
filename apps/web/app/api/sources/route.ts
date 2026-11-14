// The data sources, forwarded to the api's GET and POST /sources (admin only). A password goes to the api
// once, into the source's ClickHouse collection, and never comes back.

import { forwardJson } from "@/lib/server/api";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(request: Request): Promise<Response> {
  return forwardJson(request, "/sources");
}

export async function POST(request: Request): Promise<Response> {
  return forwardJson(request, "/sources");
}
