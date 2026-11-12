// Company documents for the console's Documents page: GET lists them and POST forwards a multipart upload
// unchanged to the api's /documents (pack_reviewer), which checks the file itself.

import { forwardBody, forwardJson } from "@/lib/server/api";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(request: Request): Promise<Response> {
  return forwardJson(request, "/documents");
}

export async function POST(request: Request): Promise<Response> {
  return forwardBody(request, "/documents");
}
