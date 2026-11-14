// Start a sign-in through the OpenID Connect provider: the api remembers the sign-in and names the
// provider address to send the browser to.

import { passThrough, rawApi } from "@/lib/server/api";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(): Promise<Response> {
  return passThrough(await rawApi("/session/oidc/start", { redirect: "manual" }));
}
