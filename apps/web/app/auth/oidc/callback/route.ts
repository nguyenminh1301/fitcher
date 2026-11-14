// The provider's redirect back, forwarded to the api, which signs the account in; its page and session
// cookie, or its redirect to the sign-in page, pass back to the browser. This is the redirect URI to
// register at the provider.

import type { NextRequest } from "next/server";

import { passThrough, rawApi } from "@/lib/server/api";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(request: NextRequest): Promise<Response> {
  return passThrough(await rawApi(`/session/oidc/callback${request.nextUrl.search}`, { redirect: "manual" }));
}
