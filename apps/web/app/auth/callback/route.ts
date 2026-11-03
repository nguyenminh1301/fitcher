// Keycloak's redirect after sign-in: the state must match the browser's sign-in cookie, then the code is
// exchanged for tokens with the PKCE verifier and a server-side session starts.

import { type NextRequest, NextResponse } from "next/server";

import { LOGIN_COOKIE, SESSION_COOKIE, authConfig, cookieOptions, finishLogin } from "@/lib/server/auth";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(request: NextRequest): Promise<Response> {
  const config = authConfig();
  const params = request.nextUrl.searchParams;
  const session = await finishLogin(config, params.get("state"), request.cookies.get(LOGIN_COOKIE)?.value, params.get("code"));
  const response = NextResponse.redirect(session ? `${config.appUrl}/` : `${config.appUrl}/sign-in?error=sign_in_failed`);
  response.cookies.delete(LOGIN_COOKIE);
  if (session) response.cookies.set(SESSION_COOKIE, session, cookieOptions(config));
  return response;
}
