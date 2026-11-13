// Whether the sign-in page offers the OpenID Connect provider, from the api's GET /session/oidc.

import { passThrough, rawApi } from "@/lib/server/api";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(): Promise<Response> {
  return passThrough(await rawApi("/session/oidc"));
}
