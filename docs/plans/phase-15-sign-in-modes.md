# Phase 15: Individual and team sign-in

## Goal

Remove Keycloak. An instance runs in individual mode with no sign-in, or in team mode with accounts kept by the application and an optional OpenID Connect provider; the mode is chosen in setup and can be raised from individual to team later (DECISIONS §9, §15).

## Scope

- One `Principal` for every request, produced by the mode in force.
- Local accounts, password hashing, server-side sessions, the Users API on local accounts.
- Host and origin checks for individual mode.
- Optional OIDC sign-in in team mode.
- Mode change and the removal of the `keycloak` service and its code.

## Out of scope

- Personal API tokens, SCIM, multi-factor authentication, password reset by email.
- More than one OIDC provider.
- Changes to pack roles or ClickHouse access control: roles keep mapping 1:1 to ClickHouse users.

## Prerequisites

- Phase 13 (app state, setup). Phase 14 is independent and may land before or after.

## Deliverables

```text
apps/api/app/auth/principal.py       # Principal and the dependency every router uses
apps/api/app/auth/accounts.py        # accounts and roles in the app state, Argon2id
apps/api/app/auth/account_sessions.py # random session ids, expiry, revocation
apps/api/app/auth/origin.py          # Host and Origin middleware
apps/api/app/auth/oidc.py            # authorization-code flow with PKCE, reusing the JWKS cache of auth/jwt.py
apps/api/app/api/session.py          # sign-in, sign-out, current user
apps/api/app/api/users.py            # rewritten on local accounts
apps/web/app/sign-in/                # sign-in page
jobs/seed_dev_accounts.py            # development accounts from a fixture file
```

## Tasks

1. **Principal (test first).** Replace the JWT principal behind `current_principal` and `current_role` with one built from the mode: the owner in individual mode, the session's account in team mode. Routers keep their role checks unchanged.
2. **Accounts and sessions (test first).** Accounts have a unique lower-cased email, display name, Argon2id hash with the library's current recommended parameters, status and roles. A session is 32 random bytes stored hashed with its account, creation and last-use times; it expires after 12 hours idle and 30 days in total and is deleted on sign-out, password change and disable. Sign-in failures are slowed per account and per address, and the error never says whether the account exists.
3. **Session cookie.** `HttpOnly`, `SameSite=Strict`, `Secure` when the request arrived over HTTPS. The web server's route handlers forward the cookie to the api and keep no session of their own: delete the in-memory store of `apps/web/lib/server/auth.ts`.
4. **Individual mode (test first).** No sign-in. The middleware accepts a request only when `Host` is `localhost`, `127.0.0.1`, `[::1]` or listed in `FITCHER_ALLOWED_HOSTS`, and a state-changing request only when `Origin` matches the host. When a non-loopback host is allowed, `/me` reports it and the interface shows the standing warning of DECISIONS §9.
5. **Users API (test first).** Create, list, disable, enable, reset password, change roles; refuse to disable or demote the last admin; write every change to `agent_logs.admin_actions`. A changed role or a disable takes effect on the user's next request. Delete `app/auth/keycloak_admin.py`.
6. **OIDC (test first).** One provider: issuer, client id, client secret (a secret of Phase 13), roles claim. Discovery, authorization-code flow with PKCE and state, ID-token validation with the existing JWKS cache. First sign-in creates the account with the claim's roles that exist in the instance, or none. Tests use a fake provider; no test needs a running identity provider.
7. **Mode change (test first).** Setup's first step creates the first admin for team mode. `PUT /setup/mode` (the endpoint setup already uses) from individual to team creates that admin and reassigns the owner's conversations, groups and feedback to it by rewriting the user id in the ReplacingMergeTree tables; team to individual is refused while more than one account is enabled.
8. **Development accounts.** `jobs.seed_dev_accounts` creates the six development users of the README from `infra/dev/accounts.yaml` with a password from `.env`, replacing `jobs.set_lab_passwords`.
9. **Remove Keycloak.** Delete the `keycloak` service, `infra/keycloak/`, the `KEYCLOAK_*` settings, the web's Keycloak flow and the image audit job. Update README (sign-in section, development users, the API example), `infra/README.md` and `.env.example`.

## Contracts

- `POST /session` with `{email, password}`, `DELETE /session`, `GET /me` (adds `mode` and `exposed`).
- `GET /session/oidc/start`, `GET /session/oidc/callback`; `GET/PUT/DELETE /settings/oidc` (admin).
- `GET /admin/users`, `POST /admin/users`, `PATCH /admin/users/{id}`, `POST /admin/users/{id}/password`.
- Environment: `FITCHER_ALLOWED_HOSTS` (comma-separated).
- App state tables `accounts`, `account_roles`, `account_sessions`, `sign_in_failures` (not `sessions`: a development pack has a column of that name, which engine code may not use).

## Verification

```bash
uv sync --project apps/api --frozen
uv run --project apps/api pytest -c apps/api/pyproject.toml
npm --prefix apps/web run typecheck && npm --prefix apps/web run test && npm --prefix apps/web run build
docker compose config --quiet && docker compose up --build --wait   # no keycloak service
curl -s -H 'Host: example.com' http://127.0.0.1:8000/me            # refused in individual mode
```

Manual check in a browser: each development user sees only its datasets and console sections, as before this phase.

## Definition of done

- Individual mode: the chat works with no sign-in; a request with a foreign `Host` or a cross-origin POST is refused.
- Team mode: the six development users sign in and get the same answers and denials as with Keycloak; restarting the stack keeps them signed in.
- `docker compose ps` lists no `keycloak` service.
- Raising an instance from individual to team keeps its conversations.

## Risks and open questions

- Rewriting the owner's rows on a mode change touches every conversation. Default: do it once, in a job reported in the setup, and keep the owner id as the first admin's id so most instances rewrite nothing.
- An instance behind a reverse proxy needs the proxy's host allowed and HTTPS detected. Default: honour `X-Forwarded-Proto` only when `FITCHER_ALLOWED_HOSTS` is set, and document it.

## Branch and PR split

`feat/api/sign-in-with-local-accounts` (principal, accounts, sessions, users), `feat/api/serve-one-owner-without-sign-in` (individual mode, mode change), `feat/api/sign-in-with-oidc`, `chore/infra/remove-keycloak` (web flow, service, docs).
