// Start a Keycloak sign-in: remember the PKCE verifier under a fresh state and send the browser to the
// realm's authorization endpoint; the state also goes into a short-lived cookie the callback checks.

import { NextResponse } from "next/server";

import { LOGIN_COOKIE, LOGIN_TTL_MS, authConfig, cookieOptions, startLogin } from "@/lib/server/auth";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export function GET(): Response {
  const config = authConfig();
  const { state, url } = startLogin(config);
  const response = NextResponse.redirect(url);
  response.cookies.set(LOGIN_COOKIE, state, cookieOptions(config, LOGIN_TTL_MS / 1000));
  return response;
}
