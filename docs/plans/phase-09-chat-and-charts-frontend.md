# Phase 9: Chat and chart frontend

## Goal

Give end users a Next.js interface: OIDC login, a streaming chat that shows each step, tables, SQL, warnings, clarify buttons and charts chosen by backend rules and rendered through a ChartSpec -> ECharts adapter, with client-side chart switching, exports and feedback.

## Scope

- Backend `chart_recommender` node implementing DECISIONS §8.
- Frontend login, chat, result panels, chart adapter, type switcher, PNG/CSV export, like/dislike.
- `feedback` writes.

## Out of scope

- Review UI (Phase 10) and Admin UI (Phase 12).

## Prerequisites

- Phases 7-8: `/ask` SSE, generated TypeScript contracts, conversation support.

## Deliverables

```text
apps/api/app/agent/nodes/chart_recommender.py
apps/api/app/api/feedback.py                     # POST /feedback
apps/web/
  app/(chat)/page.tsx
  app/api/ask/route.ts                           # server-side proxy, see open question 1
  app/api/feedback/route.ts                      # server-side proxy for feedback
  lib/auth/                                      # OIDC session
  lib/sse/parseStream.ts
  components/chat/ components/result/DataTable.tsx SqlView.tsx Warnings.tsx
  components/chart/ChartView.tsx TypeSwitcher.tsx
  lib/chart/toEChartsOption.ts allowedTypes.ts export.ts
```

## Tasks

1. **chart_recommender (test first).** Table-driven tests for every row of DECISIONS §8: KPI, line with at most 6 series, bar with horizontal switch for long labels, grouped bar, pie only for share with at most 6 non-negative groups, scatter, table fallback. `allowed_types` lists every type valid for the data; time series never allow pie. The backend decides bar orientation and records it in an optional ChartSpec field `orientation: vertical | horizontal` (open question 4), so the frontend never duplicates the rule. The `fast` tie-break runs only when two rules match equally.
2. **Auth.** OIDC authorization code with PKCE against Keycloak; session held server-side; the api call carries the access token from the server.
3. **SSE chat.** Stream parser (tests for split frames, multiple events per chunk, heartbeats); per-node status list; cancel button aborts the request.
4. **Result panels.** TanStack Table with column formats from `Result.columns`; SQL view; warning banner; clarify options as buttons that send a follow-up turn.
5. **Chart adapter (test first).** `toEChartsOption(spec, result)` pure function; tests for each chart type, series grouping by `series`, sort and number format.
6. **Type switcher.** Changes only the local ChartSpec; types outside `allowed_types` are disabled with an explanation; no network request (asserted in a test).
7. **Export.** PNG through the ECharts instance, CSV from `Result` rows.
8. **Feedback.** Like/dislike with optional note -> the `app/api/feedback` server route forwards it with the session's access token and `trace_id` -> `POST /feedback`, which rejects a `trace_id` whose run belongs to another user -> `agent_logs.feedback`. A negative test covers a foreign `trace_id`.

## Contracts

- `ChartSpec` from Phase 7; frontend imports only generated types.
- New web dependencies (pinned): `echarts`, `echarts-for-react`, `@tanstack/react-table`, an OIDC client library, a unit test runner.

## Verification

```bash
uv run --project apps/api pytest -c apps/api/pyproject.toml
npm --prefix apps/web ci
npm --prefix apps/web run typecheck
npm --prefix apps/web test
npm --prefix apps/web run build
```

Plus a manual browser check of the acceptance question, recorded with screenshots in the PR.

## Definition of done

| DoD item | Proof |
|---|---|
| Acceptance question shows a grouped bar | Recommender test and screenshot |
| Switching bar / table / line makes no API call | Component test with a network spy |
| Never a pie for a time series | Recommender test and disabled pie in the switcher |

## Risks and open questions

1. **Token handling.** Default: a Next.js server route proxies `/ask` so access tokens stay out of browser JavaScript; the browser holds only an httpOnly session cookie.
2. **OIDC library.** Default: Auth.js with the Keycloak provider; alternative: a smaller OIDC client. Decide by compatibility with the pinned Next.js version.
3. **Frontend test runner.** Default: Vitest with Testing Library; end-to-end browser tests are optional for this lab.
4. **Bar orientation in ChartSpec.** DECISIONS §7 has no orientation field. Default: add optional `orientation` to the ChartSpec contract in DECISIONS §7, with the owner's approval, in this phase's first PR, which also updates the Pydantic `ChartSpec` model and regenerates the TypeScript types with the Phase 7 generator.

## Branch and PR split

- `feat/agent/recommend-chart-types`: task 1.
- `feat/web/sign-in-and-stream-chat`: tasks 2-4.
- `feat/web/render-and-switch-charts`: tasks 5-7.
- `feat/web/record-answer-feedback`: task 8.
