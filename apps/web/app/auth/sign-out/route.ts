// End the session here and answer with the Keycloak URL that ends single sign-on and returns to sign-in.

import { type NextRequest, NextResponse } from "next/server";

import { SESSION_COOKIE, authConfig, endSession } from "@/lib/server/auth";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export function POST(request: NextRequest): Response {
  const url = endSession(authConfig(), request.cookies.get(SESSION_COOKIE)?.value);
  const response = NextResponse.json({ url }, { headers: { "cache-control": "no-store" } });
  response.cookies.delete(SESSION_COOKIE);
  return response;
}
