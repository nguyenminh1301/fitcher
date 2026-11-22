// Whether the owner password is set and this browser is signed in: GET /owner/status of the api, public.

import { passThrough, rawApi } from "@/lib/server/api";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(): Promise<Response> {
  return passThrough(await rawApi("/owner/status", { cache: "no-store" }));
}
