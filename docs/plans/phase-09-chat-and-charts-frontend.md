# Phase 9: Chat and chart frontend

## Goal

Give end users the Chat app of the Fitcher web app design ([docs/design/web-app.md](../design/web-app.md), DECISIONS §15): OIDC login, a conversation sidebar, a streaming chat that shows each step, tables, SQL, warnings, clarify buttons and charts chosen by backend rules and rendered through a ChartSpec -> ECharts adapter, with client-side chart switching, exports, feedback, message actions, an English/Vietnamese interface and light and dark themes.

## Scope

- Backend `chart_recommender` node implementing DECISIONS §8.
- Frontend login, chat, result panels, chart adapter, type switcher, PNG/CSV export, like/dislike.
- `feedback` writes.
- The design's visual system and shared components, the Chat app shell (sidebar, search, title menu, account menu) over the Phase 8 conversation endpoints, message actions, skeletons, interface language and theme.

## Out of scope

- The workspace console (Phase 10 builds its shell; Phases 10 and 12 its sections).

## Prerequisites

- Phases 7-8: `/ask` SSE, generated TypeScript contracts, conversation support.

## Deliverables

The web files listed here are created in Phase 6B on sample data; this phase adds the api side and changes them only to wire it (see Web wiring).

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
  app/styles/tokens.css                          # design tokens, light and dark
  components/ui/                                 # Button, TextField, Chip, Tabs, Menu, Dialog, Toast, Tooltip, Skeleton, ...
  components/brand/                              # Logo, Finch, Icon
  components/chat/ChatLayout.tsx SearchDialog.tsx ProgressSteps.tsx AnswerCard.tsx NoticeCard.tsx ...
  lib/i18n/en.json vi.json                       # interface strings only
  lib/steps.ts                                   # graph node -> ProgressSteps step
```

## Tasks

1. **chart_recommender (test first).** Table-driven tests for every row of DECISIONS §8: KPI, line with at most 6 series, bar with horizontal switch for long labels, grouped bar, pie only for share with at most 6 non-negative groups, scatter, table fallback. `allowed_types` lists every type valid for the data; time series never allow pie. The backend decides bar orientation and records it in an optional ChartSpec field `orientation: vertical | horizontal` (open question 4), so the frontend never duplicates the rule. The `fast` tie-break runs only when two rules match equally.
2. **Auth.** Wired in Phase 7 (see its Web wiring).
3. **SSE chat.** Wired in Phase 7 (see its Web wiring).
4. **Result panels.** Built in Phase 6B; this phase only wires it (see Web wiring).
5. **Chart adapter.** Built in Phase 6B; this phase only wires it (see Web wiring).
6. **Type switcher.** Built in Phase 6B; this phase only wires it (see Web wiring).
7. **Export.** Built in Phase 6B; this phase only wires it (see Web wiring).
8. **Feedback.** Like/dislike with optional note -> the `app/api/feedback` server route forwards it with the session's access token and `trace_id` -> `POST /feedback`, which rejects a `trace_id` whose run belongs to another user -> `agent_logs.feedback`. A negative test covers a foreign `trace_id`.
9. **Visual system.** Built in Phase 6B; this phase only wires it (see Web wiring).
10. **Chat shell.** Built in Phase 6B; this phase only wires it (see Web wiring).
11. **Answer anatomy and states.** Built in Phase 6B; this phase only wires it (see Web wiring).
12. **Message actions.** Built in Phase 6B; this phase only wires it (see Web wiring).
13. **Interface language.** Built in Phase 6B; this phase only wires it (see Web wiring).

## Contracts

- `ChartSpec` from Phase 7; frontend imports only generated types.
- New web dependencies (pinned): `echarts`, `echarts-for-react`, `@tanstack/react-table`, an OIDC client library, `lucide-react`, a unit test runner. No component library: the design's components are built in `apps/web`.

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
| Switching EN/VI changes the interface, not the answer | Component test |
| Every chat screen works at 1440, 768 and 390px in light and dark | Screenshots in the PR |

## Risks and open questions

1. **Token handling.** Default: a Next.js server route proxies `/ask` so access tokens stay out of browser JavaScript; the browser holds only an httpOnly session cookie.
2. **OIDC library.** Default: Auth.js with the Keycloak provider; alternative: a smaller OIDC client. Decide by compatibility with the pinned Next.js version.
3. **Frontend test runner.** Default: Vitest with Testing Library; end-to-end browser tests are optional for this lab.
4. **Bar orientation in ChartSpec.** DECISIONS §7 has no orientation field. Default: add optional `orientation` to the ChartSpec contract in DECISIONS §7, with the owner's approval, in this phase's first PR, which also updates the Pydantic `ChartSpec` model and regenerates the TypeScript types with the Phase 7 generator.

## Web wiring

The Phase 6B web app runs every feature on the active pack's sample data until its backend exists ([phase-06b](phase-06b-web-app-on-sample-data.md)). `apps/web/lib/api/client.ts` defines each feature's methods, `lib/api/mock/` holds the sample implementation, `lib/api/http/` the real one, and `lib/api/sources.ts` chooses between them. This phase wires:

| Feature | Mock to retire | Real endpoint | Contract | Done when |
|---|---|---|---|---|
| `chat` | the `chart_spec` events of the sample scenarios | `chart_spec` from `chart_recommender` (task 1) in the `/ask` stream | generated ChartSpec type | `sources.chat` is `http`, its Sample data badge is gone, the http client test passes and its provisional types are deleted |
| `feedback` | `mock` feedback that only updates the view | `POST /feedback` (task 8) through a server route | `FitcherApi.feedback` | `sources.feedback` is `http`, its Sample data badge is gone, the http client test passes and its provisional types are deleted |

## Branch and PR split

- `feat/agent/recommend-chart-types`: task 1.
- `feat/web/sign-in-and-stream-chat`: tasks 2-4.
- `feat/web/render-and-switch-charts`: tasks 5-7.
- `feat/web/record-answer-feedback`: task 8.
- `feat/web/build-design-system`: task 9, before tasks 2-8 use the components.
- `feat/web/manage-conversations-in-the-sidebar`: tasks 10 and 12.
- `feat/web/translate-the-interface`: tasks 11 and 13.
