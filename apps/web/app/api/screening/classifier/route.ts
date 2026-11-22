// The optional screening classifier, forwarded to the api's GET, PUT, POST and DELETE
// /screening/classifier (admin only).

import { forwardJson } from "@/lib/server/api";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(request: Request): Promise<Response> {
  return forwardJson(request, "/screening/classifier");
}

export async function POST(request: Request): Promise<Response> {
  return forwardJson(request, "/screening/classifier");
}

export async function DELETE(request: Request): Promise<Response> {
  return forwardJson(request, "/screening/classifier");
}

export async function PUT(request: Request): Promise<Response> {
  return forwardJson(request, "/screening/classifier");
}
