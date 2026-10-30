# Phase 7: API and streaming

## Goal

Expose the agent over HTTP: an authenticated `/ask` endpoint streams the DECISIONS §6 event sequence over SSE, and the QuerySpec, Result and ChartSpec contracts are published as generated TypeScript types for the frontend.

## Scope

- JWT verification against Keycloak, role mapping, `trace_id` creation, in-process rate limiting.
- `POST /ask` streaming SSE events in the fixed order.
- Pydantic -> JSON Schema -> TypeScript type generation with a CI drift check.
- `ChartSpec` contract (the recommender itself arrives in Phase 9).

## Out of scope

- Router and conversation branches (Phase 8); `/ask` runs the `data_query` flow and the deny branch.
- Frontend consumption (Phase 9).

## Prerequisites

- Phases 3-6: graph with roles, audit and tracing.

## Deliverables

```text
apps/api/app/
  auth/jwt.py                       # JWKS fetch + cache, claim validation
  auth/roles.py                     # token roles -> active pack role
  api/ask.py                        # POST /ask, SSE serialization
  api/rate_limit.py                 # per-user token bucket
  contracts/chart_spec.py
  contracts/events.py               # one model per SSE event
scripts/generate_contract_types.py  # Pydantic -> JSON Schema files
apps/web/lib/contracts/             # generated .ts files, committed
```

## Tasks

1. **JWT verification (test first).** Tests sign tokens with a local test key served through an overridden JWKS: valid token passes; expired, wrong issuer, wrong audience, bad signature and missing token give 401. JWKS responses are cached with a refresh on unknown `kid`.
2. **Role mapping.** Realm roles intersected with pack roles; no pack role -> 403; several roles -> open question 1.
3. **Event models.** `status`, `clarify`, `deny`, `sql`, `result`, `chart_spec`, `summary`, `done`, `error`, each with `trace_id`.
4. **SSE endpoint (test first).** Tests with a fake graph assert event order for success, deny, exhausted retries and internal errors (`error` is always last, nothing follows `done`). Graph node transitions emit `status` events.
5. **Cancellation.** A client disconnect cancels the graph and issues `KILL QUERY WHERE query_id = ...` for a running ClickHouse query.
6. **Rate limiting.** Per-user token bucket in process; limit exceeded -> 429 before the graph starts.
7. **Type generation.** `scripts/generate_contract_types.py` writes JSON Schemas; an npm script converts them to TypeScript under `apps/web/lib/contracts/`. CI regenerates and fails on diff.

## Contracts

- Request: `{"question": str, "conversation_id": str | null}`; header `Authorization: Bearer <JWT>`.
- SSE frames: `event: <name>` and `data: <json>`; heartbeat comments every 15 s.
- Config: `KEYCLOAK_ISSUER`, `KEYCLOAK_AUDIENCE`, `KEYCLOAK_JWKS_URL`, `RATE_LIMIT_PER_MINUTE`.

## Verification

```bash
uv run --project apps/api pytest -c apps/api/pyproject.toml
npm --prefix apps/web run typecheck
curl -N -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"question":"Top 10 best-selling products in Q1 2024 compared with Q1 2025"}' \
  http://127.0.0.1:8000/ask
```

`$TOKEN` comes from the lab realm's token endpoint for a sample user (documented in README).

## Definition of done

| DoD item | Proof |
|---|---|
| curl with a JWT receives the full event sequence | Captured stream in the PR |
| Invalid JWT -> 401 | Test and curl output |
| Role without permission -> `deny` event | Test and curl output for a restricted sample user |

## Risks and open questions

1. **Users with several pack roles.** Default: optional `X-Active-Role` header validated against the token; without it, the first pack role in policy order.
2. **SSE over POST.** Browsers' `EventSource` supports GET only. Default: keep `POST /ask` and parse the stream with `fetch` in the frontend.
3. **TypeScript generator.** Default: `json-schema-to-typescript` as a web dev dependency, pinned.
4. **Rate limits with several api workers.** In-process limits are per worker; the lab runs one worker.

## Branch and PR split

- `feat/api/verify-keycloak-tokens`: tasks 1-2.
- `feat/api/stream-ask-events`: tasks 3-6.
- `feat/api/generate-contract-types`: task 7.
