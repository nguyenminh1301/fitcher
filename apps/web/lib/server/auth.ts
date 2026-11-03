// Keycloak sign-in for the web server: OIDC authorization code with PKCE (S256), with session state held in
// server memory. The browser only gets an opaque, httpOnly session cookie; the access, refresh and ID
// tokens never leave the server. A session lives as long as the server process: a restart signs users out.

import { createHash, randomBytes } from "node:crypto";

export const SESSION_COOKIE = "fitcher_session";
export const LOGIN_COOKIE = "fitcher_login";
// A sign-in has this long to come back from Keycloak.
export const LOGIN_TTL_MS = 10 * 60 * 1000;
// An access token this close to expiry is refreshed before use.
const REFRESH_MARGIN_MS = 30 * 1000;

export type AuthConfig = {
  /** The realm as browsers reach it, which is also the issuer of its tokens. */
  issuer: string;
  /** The realm as this server reaches it (keycloak:8080 inside Compose). */
  backchannel: string;
  clientId: string;
  /** Where browsers reach this app; the sign-in callback and sign-out return here. */
  appUrl: string;
};

export function authConfig(env: Record<string, string | undefined> = process.env): AuthConfig {
  const trim = (value: string) => value.replace(/\/+$/, "");
  const issuer = trim(env.KEYCLOAK_ISSUER ?? "http://localhost:8080/realms/finch");
  return {
    issuer,
    backchannel: trim(env.KEYCLOAK_BACKCHANNEL_URL ?? issuer),
    clientId: env.KEYCLOAK_CLIENT_ID ?? "finch-web",
    appUrl: trim(env.APP_URL ?? "http://localhost:3000"),
  };
}

type TokenResponse = {
  access_token: string;
  refresh_token?: string;
  id_token?: string;
  expires_in: number;
  refresh_expires_in?: number;
};

type Session = { accessToken: string; refreshToken?: string; idToken?: string; expiresAt: number; refreshExpiresAt?: number };
type Store = {
  logins: Map<string, { verifier: string; createdAt: number }>;
  signedIn: Map<string, Session>;
  refreshing: Map<string, Promise<Session | null>>;
};

// One store per server process; globalThis keeps it across module reloads in development.
const holder = globalThis as typeof globalThis & { fitcherAuth?: Store };
const store: Store = (holder.fitcherAuth ??= { logins: new Map(), signedIn: new Map(), refreshing: new Map() });

const token = () => randomBytes(32).toString("base64url");

function prune(now: number): void {
  for (const [state, login] of store.logins) if (now - login.createdAt > LOGIN_TTL_MS) store.logins.delete(state);
  for (const [id, session] of store.signedIn) {
    const usableUntil = session.refreshToken ? session.refreshExpiresAt : session.expiresAt;
    if (usableUntil !== undefined && usableUntil <= now) store.signedIn.delete(id);
  }
}

/** Start a sign-in: the Keycloak URL to send the browser to and the state its callback must return. */
export function startLogin(config: AuthConfig, now = Date.now()): { state: string; url: string } {
  prune(now);
  const state = token();
  const verifier = token();
  store.logins.set(state, { verifier, createdAt: now });
  const url = new URL(`${config.issuer}/protocol/openid-connect/auth`);
  url.search = new URLSearchParams({
    client_id: config.clientId,
    response_type: "code",
    scope: "openid",
    redirect_uri: `${config.appUrl}/auth/callback`,
    state,
    code_challenge: createHash("sha256").update(verifier).digest("base64url"),
    code_challenge_method: "S256",
  }).toString();
  return { state, url: url.toString() };
}

async function requestTokens(config: AuthConfig, form: Record<string, string>): Promise<TokenResponse | null> {
  const response = await fetch(`${config.backchannel}/protocol/openid-connect/token`, {
    method: "POST",
    headers: { "content-type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({ client_id: config.clientId, ...form }),
    cache: "no-store",
  });
  if (!response.ok) return null;
  const body = (await response.json()) as TokenResponse;
  return typeof body.access_token === "string" ? body : null;
}

function toSession(tokens: TokenResponse, now: number, previous?: Session): Session {
  const refreshTtl = tokens.refresh_expires_in;
  return {
    accessToken: tokens.access_token,
    refreshToken: tokens.refresh_token ?? previous?.refreshToken,
    idToken: tokens.id_token ?? previous?.idToken,
    expiresAt: now + tokens.expires_in * 1000,
    // Keycloak reports 0 for a refresh token without its own expiry.
    refreshExpiresAt: refreshTtl ? now + refreshTtl * 1000 : previous?.refreshExpiresAt,
  };
}

/** Finish a sign-in: exchange the code with the state's PKCE verifier; the new session id, or null. */
export async function finishLogin(
  config: AuthConfig, state: string | null, cookieState: string | undefined, code: string | null, now = Date.now(),
): Promise<string | null> {
  if (!state || !code || state !== cookieState) return null;
  const login = store.logins.get(state);
  store.logins.delete(state);
  if (!login || now - login.createdAt > LOGIN_TTL_MS) return null;
  const tokens = await requestTokens(config, {
    grant_type: "authorization_code", code, redirect_uri: `${config.appUrl}/auth/callback`, code_verifier: login.verifier,
  });
  if (!tokens) return null;
  const id = token();
  store.signedIn.set(id, toSession(tokens, now));
  return id;
}

/** The session's access token, refreshed first when it is about to expire; null when signed out. */
export async function accessToken(config: AuthConfig, id: string | undefined, now = Date.now()): Promise<string | null> {
  const session = id ? store.signedIn.get(id) : undefined;
  if (!id || !session) return null;
  if (session.expiresAt - REFRESH_MARGIN_MS > now) return session.accessToken;
  let pending = store.refreshing.get(id);
  if (!pending) {
    pending = (async () => {
      const tokens = session.refreshToken ? await requestTokens(config, { grant_type: "refresh_token", refresh_token: session.refreshToken }) : null;
      if (!tokens) {
        store.signedIn.delete(id);
        return null;
      }
      const next = toSession(tokens, now, session);
      store.signedIn.set(id, next);
      return next;
    })().finally(() => store.refreshing.delete(id));
    store.refreshing.set(id, pending);
  }
  return (await pending)?.accessToken ?? null;
}

/** End the session; the Keycloak URL that ends the single sign-on session and returns to sign-in. */
export function endSession(config: AuthConfig, id: string | undefined): string {
  const session = id ? store.signedIn.get(id) : undefined;
  if (id) store.signedIn.delete(id);
  const url = new URL(`${config.issuer}/protocol/openid-connect/logout`);
  const params: Record<string, string> = { client_id: config.clientId, post_logout_redirect_uri: `${config.appUrl}/sign-in` };
  if (session?.idToken) params.id_token_hint = session.idToken;
  url.search = new URLSearchParams(params).toString();
  return url.toString();
}

/** Forget a session the api no longer accepts. */
export function dropSession(id: string | undefined): void {
  if (id) store.signedIn.delete(id);
}

/** Cookie options: httpOnly, same-site lax, secure when the app is served over https. */
export function cookieOptions(config: AuthConfig, maxAgeSeconds?: number) {
  return {
    httpOnly: true, sameSite: "lax" as const, path: "/", secure: config.appUrl.startsWith("https://"),
    ...(maxAgeSeconds !== undefined ? { maxAge: maxAgeSeconds } : {}),
  };
}
