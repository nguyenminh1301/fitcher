// An uploaded data file (CSV, XLSX or Parquet), forwarded as the multipart body it came as to the api's
// POST /sources/files (admin only).

import { forwardBody } from "@/lib/server/api";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function POST(request: Request): Promise<Response> {
  return forwardBody(request, "/sources/files");
}
